from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from test_cli_boundaries import cli_files
from test_edge_boundaries import AGENT_TOKEN, tool
from test_store_authority import TOKEN
from test_store_authority import authority as authority

from agents_memory import cli, ingress
from agents_memory.config import Settings
from agents_memory.domain import DomainError, EffectState, Role
from agents_memory.edge import actor_from_scope, create_app
from agents_memory.ingress import (
    OAUTH_METADATA_PATH,
    ClientBootstrapResult,
    CloudIngressProfile,
    OAuthIdentityMapping,
    OAuthResourceProfile,
    OAuthVerifier,
    configure_ingress,
    load_ingress,
)
from agents_memory.private_io import private_write
from agents_memory.store import Store

PUBLIC_ORIGIN = "https://memory.example.test"
ISSUER = "https://identity.example.test/tenant"
NOW = 2000000000
PRODUCER_TOKEN = "cloud-producer-credential-" + "p" * 40


@pytest.fixture
def signing(monkeypatch):
    key = ec.derive_private_key(123456789, ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", alg="ES256", use="sig")

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(NOW, tz=tz or UTC)

    monkeypatch.setattr("jwt.api_jwt.datetime", FrozenDatetime)
    monkeypatch.setattr("agents_memory.ingress.time.time", lambda: NOW)
    return key, public


def access_token(signing, *, claims=None, headers=None, key=None):
    payload = {
        "iss": ISSUER, "aud": PUBLIC_ORIGIN, "sub": "agent-subject", "client_id": "native-client",
        "iat": NOW - 10, "exp": NOW + 300, "jti": "request-token", "scope": "memory.agent",
    }
    payload.update(claims or {})
    return jwt.encode(payload, key or signing[0], algorithm="ES256", headers={"typ": "at+jwt", "kid": "test-key", **(headers or {})})


def profile(settings, *, oauth=None, **changes):
    return CloudIngressProfile(
        deployment_id=settings.deployment_id, realm=settings.realm, public_origin=PUBLIC_ORIGIN,
        auth_mode="oauth" if oauth is not None else "bearer", tls_proxy="loopback", oauth=oauth, **changes,
    )


def oauth_profile(signing, agent, producer=None, *, extra=()):
    mappings = [OAuthIdentityMapping(subject="agent-subject", client_id="native-client", required_scopes=("memory.agent",), credential_id=agent.credential_id, generation=agent.generation)]
    if producer is not None:
        mappings.append(OAuthIdentityMapping(subject="producer-subject", client_id="capture-client", required_scopes=("memory.capture",), credential_id=producer.credential_id, generation=producer.generation))
    return OAuthResourceProfile(issuer=ISSUER, audience=PUBLIC_ORIGIN, algorithms=("ES256",),
                                jwks={"keys": [signing[1]]}, mappings=tuple(mappings) + extra)


async def request(edge, payload=None, token=None, *, path="/api/client-bootstrap", method="POST", host="memory.example.test", scheme="http", peer="127.0.0.1", forwarded=((b"x-forwarded-proto", b"https"),), extra_headers=(), protocol_version="2026-07-28"):
    headers = [(b"host", host.encode()), (b"content-type", b"application/json"),
               (b"accept", b"application/json, text/event-stream"),
               (b"mcp-protocol-version", protocol_version.encode()), *forwarded, *extra_headers]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if path == "/mcp" and isinstance(payload, dict):
        headers.append((b"mcp-method", payload["method"].encode()))
        if isinstance(payload.get("params", {}).get("name"), str):
            headers.append((b"mcp-name", payload["params"]["name"].encode()))
    incoming = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": json.dumps(payload or {}).encode(), "more_body": False})
    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
        "scheme": scheme, "method": method, "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "server": ("127.0.0.1", 8768),
        "client": None if peer is None else (peer, 59999), "headers": headers, "state": {},
    }
    await asyncio.wait_for(edge(scope, incoming.get, send), 10)
    starts = [item for item in messages if item["type"] == "http.response.start"]
    assert len(starts) == 1
    body = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
    return starts[0]["status"], json.loads(body) if body else {}, dict(starts[0].get("headers", ()))


@asynccontextmanager
async def running(authority, signing=None, *, extra_mapping=False):
    settings = authority.store.settings
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.state_dir.chmod(0o700)
    agent = await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    producer = await authority.store.issue_token(authority.actor, Role.PRODUCER, (authority.binding_id,), PRODUCER_TOKEN)
    extra = ()
    if extra_mapping:
        extra = (OAuthIdentityMapping(subject="second-subject", client_id="native-client", required_scopes=("memory.agent",), credential_id=agent.credential_id, generation=agent.generation),)
    configured = profile(settings, oauth=oauth_profile(signing, agent, producer, extra=extra) if signing else None)
    configure_ingress(settings, configured)
    edge = create_app(settings)
    async with edge.inner.router.lifespan_context(edge.inner):
        yield edge, agent, producer


def settings(tmp_path):
    return Settings(deployment_id="test-deployment", realm="test-realm", mode="company", database_dsn="postgresql://not-used", state_dir=tmp_path / "state", journal_dir=tmp_path / "journal")


def test_absent_ingress_preserves_settings_shape_and_private_roundtrip(tmp_path):
    configured = settings(tmp_path)
    before = configured.model_dump_json()
    assert load_ingress(configured) is None
    ingress = profile(configured)
    path = configure_ingress(configured, ingress)
    assert path == configured.state_dir / "cloud" / "ingress.json"
    assert path.stat().st_mode & 0o077 == 0
    assert load_ingress(configured) == ingress
    assert configured.model_dump_json() == before


@pytest.mark.parametrize("change", [{"version": 2}, {"version": True}, {"auth_mode": "oauth"}, {"public_origin": "http://memory.example.test"}, {"public_origin": "https://memory.example.test/path"}, {"unexpected": True}])
def test_invalid_ingress_fails_closed(tmp_path, change):
    value = profile(settings(tmp_path)).model_dump(mode="json") | change
    with pytest.raises(ValueError):
        CloudIngressProfile.model_validate_json(json.dumps(value))


def test_wrong_deployment_and_unsafe_sidecar_fail_closed(tmp_path):
    configured = settings(tmp_path)
    wrong = profile(configured).model_copy(update={"realm": "another-realm"})
    with pytest.raises(DomainError):
        configure_ingress(configured, wrong)
    path = configure_ingress(configured, profile(configured))
    path.chmod(0o644)
    with pytest.raises(DomainError, match="ingress"):
        load_ingress(configured)


@pytest.mark.parametrize("mutation", ["private", "missing", "ambiguous", "symmetric", "unknown-algorithm"])
def test_oauth_configuration_requires_public_keys_and_unambiguous_mapping(signing, mutation):
    value = {
        "issuer": ISSUER, "audience": PUBLIC_ORIGIN, "algorithms": ["ES256"], "jwks": {"keys": [dict(signing[1])]},
        "mappings": [{"subject": "agent-subject", "client_id": "native-client", "required_scopes": ["memory.agent"], "credential_id": "credential-test", "generation": 1}],
    }
    if mutation == "private":
        value["jwks"]["keys"][0]["d"] = "private"
    elif mutation == "missing":
        value["jwks"]["keys"] = []
    elif mutation == "ambiguous":
        value["mappings"] *= 2
    elif mutation == "symmetric":
        value["jwks"] = {"keys": [{"kty": "oct", "kid": "test-key", "alg": "HS256", "k": "private"}]}
    else:
        value["algorithms"] = ["HS256"]
    with pytest.raises(ValueError):
        OAuthResourceProfile.model_validate_json(json.dumps(value))


async def test_bearer_bootstrap_returns_only_current_one_binding_identity_and_bounds(authority):
    async with running(authority) as (edge, agent, producer):
        for token, actor in ((AGENT_TOKEN, agent), (PRODUCER_TOKEN, producer)):
            status, body, _ = await request(edge, {"binding_id": authority.binding_id}, token)
            result = ClientBootstrapResult.model_validate(body)
            assert status == 200 and result.auth_mode == "bearer"
            assert (result.credential_id, result.generation, result.role) == (actor.credential_id, actor.generation, actor.role.value)
            assert result.bindings == (authority.binding_id,) and result.binding_revision == 1
            assert result.bounds.max_http_body_bytes == authority.store.settings.max_http_body_bytes
            assert set(body) == set(ClientBootstrapResult.model_fields)
            for private in (TOKEN, AGENT_TOKEN, PRODUCER_TOKEN, authority.store.settings.database_dsn, str(authority.store.settings.journal_dir)):
                assert private not in json.dumps(body)
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, TOKEN)
        assert status == 403
        status, _, _ = await request(edge, {"binding_id": "binding-missing"}, AGENT_TOKEN)
        assert status == 403
        status, _, _ = await request(edge, {"binding_id": authority.binding_id, "project": "/pc/private"}, AGENT_TOKEN)
        assert status == 400


async def test_bootstrap_rejects_multibinding_credential_without_stating_pc_locator(authority):
    async with running(authority) as (edge, agent, _):
        second = await authority.store.register_binding(authority.actor, "Other project", "/not-a-cloud-file", "second-binding")
        await authority.store.grant_binding(authority.actor, agent.credential_id, second.id)
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN)
        assert status == 403


@pytest.mark.parametrize("overrides,expected", [
    ({"forwarded": ()}, 403),
    ({"peer": "198.51.100.10"}, 403),
    ({"forwarded": ((b"x-forwarded-proto", b"http"),)}, 403),
    ({"forwarded": ((b"x-forwarded-proto", b"https,http"),)}, 403),
    ({"extra_headers": ((b"x-forwarded-proto", b"https"),)}, 400),
    ({"extra_headers": ((b"x-forwarded-host", b"memory.example.test"),)}, 400),
    ({"extra_headers": ((b"forwarded", b"proto=https"),)}, 400),
    ({"extra_headers": ((b"origin", b"https://evil.example.test"),)}, 403),
    ({"extra_headers": ((b"origin", PUBLIC_ORIGIN.encode()), (b"origin", PUBLIC_ORIGIN.encode()))}, 400),
    ({"host": "evil.example.test"}, 403),
])
async def test_public_tls_and_forwarded_security_headers_fail_closed(authority, overrides, expected):
    async with running(authority) as (edge, _, _):
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, **overrides)
        assert status == expected


async def test_direct_asgi_https_and_local_bearer_remain_valid(authority):
    async with running(authority) as (edge, _, _):
        for options in ({"scheme": "https", "forwarded": (), "peer": "198.51.100.10"}, {"host": "127.0.0.1:8768", "forwarded": ()}):
            status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, **options)
            assert status == 200
        status, _, _ = await request(edge, path=OAUTH_METADATA_PATH, method="GET")
        assert status == 404


async def test_private_proxy_accepts_only_its_exact_peer_and_rejects_local_host_spoofing(authority):
    configured = authority.store.settings
    configured.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    configured.state_dir.chmod(0o700)
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    ingress = CloudIngressProfile.model_validate({
        **profile(configured).model_dump(mode="python"), "tls_proxy": "private", "trusted_proxy_ip": "172.24.0.3",
    })
    configure_ingress(configured, ingress)
    edge = create_app(configured)
    async with edge.inner.router.lifespan_context(edge.inner):
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, peer="172.24.0.3")
        assert status == 200 and body["role"] == "agent" and body["deployment_id"] == configured.deployment_id
        for overrides, expected in (
            ({"peer": "172.24.0.4"}, 403),
            ({"peer": "127.0.0.1"}, 403),
            ({"peer": "172.24.0.3", "forwarded": ()}, 403),
            ({"peer": "172.24.0.3", "extra_headers": ((b"x-forwarded-for", b"172.24.0.3"),)}, 400),
            ({"peer": "172.24.0.4", "host": "127.0.0.1:8768", "forwarded": ()}, 403),
        ):
            status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, **overrides)
            assert status == expected
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN,
                                        host="127.0.0.1:8768", forwarded=())
        assert status == 200 and body["role"] == "agent"


@pytest.mark.parametrize("change", [
    {"tls_proxy": "private"},
    {"tls_proxy": "private", "trusted_proxy_ip": "8.8.8.8"},
    {"tls_proxy": "private", "trusted_proxy_ip": "127.0.0.1"},
    {"tls_proxy": "private", "trusted_proxy_ip": "172.24.0.0/24"},
    {"tls_proxy": "loopback", "trusted_proxy_ip": "172.24.0.3"},
])
def test_private_proxy_configuration_never_infers_a_network_or_unused_trust(tmp_path, change):
    configured = profile(settings(tmp_path)).model_dump(mode="json") | change
    with pytest.raises(ValueError):
        CloudIngressProfile.model_validate_json(json.dumps(configured))


async def test_oauth_bootstrap_uses_verified_identity_and_actual_pg_role(authority, signing):
    async with running(authority, signing) as (edge, agent, producer):
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, access_token(signing, claims={"roles": ["operator"]}))
        assert status == 200 and body["auth_mode"] == "oauth" and body["role"] == "agent"
        assert body["credential_id"] == agent.credential_id
        token = access_token(signing, claims={"sub": "producer-subject", "client_id": "capture-client", "scope": "memory.capture", "roles": ["agent"]})
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, token)
        assert status == 200 and body["role"] == "producer" and body["credential_id"] == producer.credential_id
        status, _, _ = await request(edge, tool({"binding_id": authority.binding_id, "query": "private"}), token, path="/mcp")
        assert status == 403
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN)
        assert status == 401
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, host="127.0.0.1:8768", forwarded=())
        assert status == 200 and body["auth_mode"] == "bearer"


@pytest.mark.parametrize("claims,headers", [
    ({"iss": "https://wrong.example.test"}, {}), ({"aud": "https://wrong.example.test"}, {}),
    ({"aud": [PUBLIC_ORIGIN]}, {}), ({"exp": NOW}, {}), ({"exp": str(NOW + 300)}, {}),
    ({"iat": NOW + 1}, {}), ({"nbf": NOW + 1}, {}), ({"sub": "unmapped"}, {}),
    ({"client_id": "unmapped"}, {}), ({"scope": "memory.capture"}, {}),
    ({"jti": ""}, {}), ({"scope": "memory.agent memory.agent"}, {}),
    ({}, {"typ": "JWT"}), ({}, {"typ": "id+jwt"}), ({}, {"kid": "unknown"}),
    ({}, {"jku": "https://attacker.example.test/keys"}),
])
async def test_oauth_rejects_invalid_token_profile_before_bootstrap(authority, signing, claims, headers):
    async with running(authority, signing) as (edge, _, _):
        status, _, response_headers = await request(edge, {"binding_id": authority.binding_id}, access_token(signing, claims=claims, headers=headers))
        assert status == 401
        assert b"resource_metadata" in response_headers[b"www-authenticate"]


async def test_oauth_wrong_signature_and_current_generation_revocation_fail(authority, signing):
    async with running(authority, signing) as (edge, agent, _):
        wrong = ec.derive_private_key(987654321, ec.SECP256R1())
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, access_token(signing, key=wrong))
        assert status == 401
        await authority.store.revoke_token(authority.actor, agent.credential_id)
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, access_token(signing))
        assert status == 401


async def test_handler_reauthenticates_current_external_generation_and_grants(authority, signing):
    async with running(authority, signing) as (edge, agent, _):
        verifier = OAuthVerifier(edge.ingress.oauth, authority.store)
        _, identity = await verifier.authenticate(access_token(signing))
        current = await actor_from_scope(edge.application, {"agents_memory_oauth": identity}, (Role.AGENT,))
        assert current.credential_id == agent.credential_id
        with pytest.raises(DomainError):
            await authority.store.authenticate_external(agent.credential_id, agent.generation + 1)
        with pytest.raises(DomainError):
            await actor_from_scope(edge.application, {"agents_memory_oauth": identity}, (Role.PRODUCER,))
        await authority.store.revoke_token(authority.actor, agent.credential_id)
        with pytest.raises(DomainError):
            await actor_from_scope(edge.application, {"agents_memory_oauth": identity}, (Role.AGENT,))


async def test_oauth_metadata_and_challenge_are_public_origin_only(authority, signing):
    async with running(authority, signing) as (edge, _, _):
        status, metadata, _ = await request(edge, path=OAUTH_METADATA_PATH, method="GET")
        assert status == 200 and metadata["resource"] == PUBLIC_ORIGIN
        assert metadata["authorization_servers"] == [ISSUER]
        assert "token_endpoint" not in metadata and "jwks" not in metadata
        status, _, _ = await request(edge, path=OAUTH_METADATA_PATH, method="GET", host="127.0.0.1:8768", forwarded=())
        assert status == 404
        status, _, response_headers = await request(edge, {"binding_id": authority.binding_id})
        assert status == 401 and (PUBLIC_ORIGIN + OAUTH_METADATA_PATH).encode() in response_headers[b"www-authenticate"]


async def test_edge_and_sdk_sessions_bind_issuer_subject_client_not_only_credential(authority, signing):
    async with running(authority, signing, extra_mapping=True) as (edge, _, _):
        initial = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "cloud-test", "version": "1"}}}
        status, _, headers = await request(edge, initial, access_token(signing), path="/mcp", protocol_version="2025-11-25")
        assert status == 200
        session = headers[b"mcp-session-id"]
        payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        status, _, _ = await request(edge, payload, access_token(signing, claims={"sub": "second-subject"}), path="/mcp", protocol_version="2025-11-25", extra_headers=((b"mcp-session-id", session),))
        assert status == 403
        owner, timestamp = edge.sessions[session.decode()]
        edge.sessions[session.decode()] = ((*owner[:4], "second-subject", owner[-1]), timestamp)
        status, _, _ = await request(edge, payload, access_token(signing, claims={"sub": "second-subject"}), path="/mcp", protocol_version="2025-11-25", extra_headers=((b"mcp-session-id", session),))
        assert status == 404


def test_malformed_ingress_never_falls_back_to_local(tmp_path):
    configured = settings(tmp_path)
    configure_ingress(configured, profile(configured))
    private_write(configured.state_dir / "cloud" / "ingress.json", '{"version":1,"auth_mode":"oauth"}', replace=True)
    with pytest.raises(DomainError):
        create_app(configured)


async def test_bootstrap_does_not_stat_cloud_or_pc_binding_locator(authority):
    async with running(authority) as (edge, _, _):
        binding = await authority.store.register_binding(
            authority.actor, "Explicit PC association", "/this/pc/path/does/not/exist/on/cloud", "pc-binding",
        )
        token = "single-pc-agent-credential-" + "q" * 40
        await authority.store.issue_token(authority.actor, Role.AGENT, (binding.id,), token)
        status, body, _ = await request(edge, {"binding_id": binding.id}, token)
        assert status == 200 and body["binding_revision"] == 1 and body["bindings"] == [binding.id]
        assert "locator" not in body


async def test_oauth_reloads_current_grants_before_binding_disclosure(authority, signing):
    async with running(authority, signing) as (edge, agent, _):
        token = access_token(signing)
        async with authority.store.pool.acquire() as connection:
            await connection.execute("DELETE FROM am_grants WHERE credential_id=$1", agent.credential_id)
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, token)
        assert status == 403


async def test_public_origin_is_denied_without_profile_or_explicit_proxy_declaration(authority):
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    edge = create_app(authority.store.settings)
    async with edge.inner.router.lifespan_context(edge.inner):
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN)
        assert status == 403
    configured = profile(authority.store.settings).model_copy(update={"tls_proxy": "none"})
    configure_ingress(authority.store.settings, configured)
    edge = create_app(authority.store.settings)
    async with edge.inner.router.lifespan_context(edge.inner):
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN)
        assert status == 403
        status, _, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, scheme="https", forwarded=())
        assert status == 200


async def test_public_ingress_rejects_operator_while_loopback_control_remains_available(authority):
    async with running(authority) as (edge, _, _):
        status, body, _ = await request(edge, token=TOKEN, path="/readyz", method="GET")
        assert status == 403 and body["error"]["code"] == "ROLE_DENIED"
        status, body, _ = await request(
            edge, token=TOKEN, path="/readyz", method="GET", host="127.0.0.1:8768", forwarded=(),
        )
        assert status == 200 and body["ready"] is True and body["db_ready"] is True


async def test_authentication_failure_precedes_unavailable_journal(authority, monkeypatch):
    async with running(authority) as (edge, _, _):
        def unavailable_journal(*args, **kwargs):
            raise DomainError("JOURNAL_UNAVAILABLE", "The deletion authority is unavailable", status=503)

        monkeypatch.setattr(edge.application.store.journal, "verify", unavailable_journal)
        for token in (None, "bad token"):
            status, body, _ = await request(edge, {"binding_id": authority.binding_id}, token)
            assert status == 401 and body["error"]["code"] == "UNAUTHORIZED"
        status, body, _ = await request(edge, {"binding_id": authority.binding_id}, AGENT_TOKEN)
        assert status == 503 and body["error"]["code"] == "JOURNAL_UNAVAILABLE"


@pytest.mark.parametrize("proxy,peer,host", [
    (None, "198.51.100.10", "127.0.0.1:8768"),
    ("none", "2001:db8::10", "localhost:8768"),
    ("loopback", "198.51.100.10", "localhost:8768"),
    ("private", "172.24.0.3", "127.0.0.1:8768"),
    ("none", None, "127.0.0.1:8768"),
    (None, "localhost", "localhost:8768"),
])
async def test_local_authority_hosts_require_an_actual_loopback_peer(authority, proxy, peer, host):
    configured = authority.store.settings
    await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    if proxy is not None:
        ingress = CloudIngressProfile.model_validate({
            **profile(configured).model_dump(mode="python"), "tls_proxy": proxy,
            "trusted_proxy_ip": "172.24.0.3" if proxy == "private" else None,
        })
        configure_ingress(configured, ingress)
    edge = create_app(configured)
    async with edge.inner.router.lifespan_context(edge.inner):
        for path, method, token, payload in (
            ("/readyz", "GET", TOKEN, None),
            ("/api/client-bootstrap", "POST", AGENT_TOKEN, {"binding_id": authority.binding_id}),
        ):
            status, body, _ = await request(
                edge, payload, token, path=path, method=method, host=host,
                peer=peer, forwarded=(), extra_headers=((b"origin", ("http://" + host).encode()),),
            )
            assert status == 403
            assert body["error"]["code"] == "HOST_ORIGIN_DENIED"
            assert body["error"]["effect"] == "not_started"
        status, body, _ = await request(
            edge, token=TOKEN, path="/readyz", method="GET", host=host, peer="::1", forwarded=(),
        )
        assert status == 200 and body["ready"] is True and body["db_ready"] is True
        status, body, _ = await request(
            edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, host=host, peer="127.0.0.1", forwarded=(),
        )
        assert status == 200 and body["role"] == "agent" and body["bindings"] == [authority.binding_id]


async def test_no_proxy_oauth_cannot_be_downgraded_by_a_spoofed_local_host(authority, signing):
    configured = authority.store.settings
    agent = await authority.store.issue_token(authority.actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    ingress = profile(configured, oauth=oauth_profile(signing, agent)).model_copy(update={"tls_proxy": "none"})
    configure_ingress(configured, ingress)
    edge = create_app(configured)
    async with edge.inner.router.lifespan_context(edge.inner):
        status, body, _ = await request(
            edge, {"binding_id": authority.binding_id}, AGENT_TOKEN, host="localhost:8768",
            peer="198.51.100.10", forwarded=(),
        )
        assert status == 403 and body["error"]["code"] == "HOST_ORIGIN_DENIED"
        status, body, _ = await request(
            edge, token=TOKEN, path="/readyz", method="GET", host="127.0.0.1:8768",
            peer="198.51.100.10", forwarded=(),
        )
        assert status == 403 and body["error"]["code"] == "HOST_ORIGIN_DENIED"
        status, body, _ = await request(
            edge, {"binding_id": authority.binding_id}, access_token(signing),
            scheme="https", peer="198.51.100.10", forwarded=(),
        )
        assert status == 200 and body["role"] == "agent" and body["bindings"] == [authority.binding_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_mode", ("bearer", "oauth"))
@pytest.mark.parametrize("mutation", ("current", "revoked", "generation"))
@pytest.mark.parametrize("existing", (False, True))
async def test_cli_ingress_publication_uses_current_operator(
    authority, signing, tmp_path, monkeypatch, auth_mode, mutation, existing,
):
    store, actor = authority.store, authority.actor
    configured = store.settings
    configured.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    agent = await store.issue_token(actor, Role.AGENT, (authority.binding_id,), AGENT_TOKEN)
    candidate = profile(configured, oauth=oauth_profile(signing, agent) if auth_mode == "oauth" else None)
    destination = configured.state_dir / "cloud" / "ingress.json"
    prior = None
    if existing:
        configure_ingress(configured, profile(configured).model_copy(update={"public_origin": "https://previous.example.test"}))
        prior = destination.read_bytes()
    input_file = tmp_path / "ingress-profile.json"
    private_write(input_file, candidate.model_dump_json())
    args = cli.parser().parse_args(cli_files(authority, tmp_path) + [
        "cloud", "configure", "--ingress-file", str(input_file), "--ack-remote-storage",
    ])
    entered, release = asyncio.Event(), asyncio.Event()
    authenticate, authenticate_external = Store.authenticate, Store.authenticate_external
    task = None

    async def pause_after_authentication(self, token):
        current = await authenticate(self, token)
        if auth_mode == "bearer" and asyncio.current_task() is task:
            entered.set()
            await release.wait()
        return current

    async def pause_after_mapping(self, *values, **options):
        current = await authenticate_external(self, *values, **options)
        if auth_mode == "oauth" and asyncio.current_task() is task:
            entered.set()
            await release.wait()
        return current

    monkeypatch.setattr(Store, "authenticate", pause_after_authentication)
    monkeypatch.setattr(Store, "authenticate_external", pause_after_mapping)
    task = asyncio.create_task(cli.execute(args))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if mutation == "revoked":
            await store.revoke_token(actor, actor.credential_id)
        elif mutation == "generation":
            async with store._tx() as (connection, _):
                await connection.execute("UPDATE am_credentials SET generation=generation+1 WHERE id=$1", actor.credential_id)
        release.set()
        outcome = (await asyncio.gather(task, return_exceptions=True))[0]
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if mutation == "current":
        assert not isinstance(outcome, BaseException)
        assert load_ingress(configured) == candidate
    else:
        assert isinstance(outcome, DomainError)
        assert outcome.code == ("AUTH_DENIED" if mutation == "revoked" else "SCOPE_DENIED")
        assert outcome.effect == EffectState.NOT_STARTED
        assert (destination.read_bytes() if destination.exists() else None) == prior


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("file_response", "authority_domain", "authority_os"))
async def test_cli_ingress_publication_preserves_durable_effect(
    authority, tmp_path, monkeypatch, failure,
):
    configured = authority.store.settings
    configured.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate = profile(configured)
    destination = configured.state_dir / "cloud" / "ingress.json"
    input_file = tmp_path / "ingress-profile.json"
    private_write(input_file, candidate.model_dump_json())
    args = cli.parser().parse_args(cli_files(authority, tmp_path) + [
        "cloud", "configure", "--ingress-file", str(input_file), "--ack-remote-storage",
    ])
    if failure == "file_response":
        write = ingress.private_write

        def lose_file_response(path, content, **options):
            write(path, content, **options)
            if path == destination:
                raise OSError("synthetic lost ingress write response")

        monkeypatch.setattr(ingress, "private_write", lose_file_response)
    else:
        operator_authority = Store.operator_authority

        @asynccontextmanager
        async def lose_authority_response(self, actor):
            async with operator_authority(self, actor) as current:
                yield current
            if failure == "authority_domain":
                raise DomainError("DATABASE_UNAVAILABLE", "synthetic lost authority response", effect=EffectState.UNKNOWN)
            raise OSError("synthetic lost authority release response")

        monkeypatch.setattr(Store, "operator_authority", lose_authority_response)
    with pytest.raises(DomainError) as interrupted:
        await cli.execute(args)
    assert load_ingress(configured) == candidate
    assert interrupted.value.effect == (EffectState.UNKNOWN if failure == "file_response" else EffectState.COMMITTED)
    if failure == "authority_domain":
        assert interrupted.value.code == "DATABASE_UNAVAILABLE"
