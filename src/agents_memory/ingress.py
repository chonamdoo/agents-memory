from __future__ import annotations

import ipaddress
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken
from pydantic import ConfigDict, Field, field_validator, model_validator

from .config import Settings
from .connection import https_origin
from .domain import DomainError, Handle, Principal, TypedModel
from .private_io import private_read, private_write
from .wire import decode_json, validate_wire

INGRESS_MAX_BYTES = 131072
OAUTH_METADATA_PATH = "/.well-known/oauth-protected-resource"


class OAuthIdentityMapping(TypedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    subject: str = Field(min_length=1, max_length=512)
    client_id: str = Field(min_length=1, max_length=256)
    required_scopes: tuple[str, ...] = Field(min_length=1, max_length=16)
    credential_id: Handle
    generation: int = Field(ge=1)

    @field_validator("required_scopes")
    @classmethod
    def valid_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(
            not scope or len(scope) > 128 or any(ord(c) < 33 or ord(c) > 126 or c in '\\"' for c in scope)
            for scope in value
        ):
            raise ValueError("Required OAuth scopes must be distinct bounded scope tokens")
        return value


class OAuthResourceProfile(TypedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    issuer: str = Field(min_length=1, max_length=2048)
    audience: str = Field(min_length=1, max_length=2048)
    algorithms: tuple[Literal["RS256", "ES256"], ...] = ("RS256",)
    jwks: dict = Field(repr=False)
    mappings: tuple[OAuthIdentityMapping, ...] = Field(min_length=1, max_length=128)

    @field_validator("issuer")
    @classmethod
    def valid_issuer(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            origin = https_origin(f"https://{parsed.netloc}")
        except DomainError:
            raise ValueError("The issuer requires a canonical HTTPS origin") from None
        if (parsed.scheme != "https" or parsed.query or parsed.fragment
                or value != origin + parsed.path or any(c.isspace() for c in value)):
            raise ValueError("The issuer must be an exact canonical credential-free HTTPS URL")
        return value

    @model_validator(mode="after")
    def bounded_public_keys(self) -> OAuthResourceProfile:
        if not self.algorithms or len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("Choose distinct supported asymmetric algorithms")
        if set(self.jwks) != {"keys"} or not isinstance(self.jwks["keys"], list) or not 1 <= len(self.jwks["keys"]) <= 16:
            raise ValueError("Supply a bounded public JWKS key set")
        if len(json.dumps(self.jwks, allow_nan=False).encode()) > 65536:
            raise ValueError("The public JWKS exceeds its bound")
        identifiers = set()
        for key in self.jwks["keys"]:
            if not isinstance(key, dict) or not isinstance(key.get("kid"), str) or not 1 <= len(key["kid"]) <= 128:
                raise ValueError("Each verification key requires a bounded key ID")
            if key["kid"] in identifiers:
                raise ValueError("Verification key IDs must be unique")
            identifiers.add(key["kid"])
            algorithm = key.get("alg")
            if algorithm not in self.algorithms or key.get("use", "sig") != "sig" or key.get("key_ops", ["verify"]) != ["verify"]:
                raise ValueError("Verification keys require an allowed signing algorithm and verify-only usage")
            fields = {"kty", "kid", "alg", "use", "key_ops"}
            if algorithm == "RS256":
                if key.get("kty") != "RSA" or set(key) - (fields | {"n", "e"}):
                    raise ValueError("Only public RSA verification material is accepted")
            elif key.get("kty") != "EC" or key.get("crv") != "P-256" or set(key) - (fields | {"crv", "x", "y"}):
                raise ValueError("Only public P-256 verification material is accepted")
            try:
                parsed = jwt.PyJWK.from_dict(key, algorithm=algorithm)
                if algorithm == "RS256" and not 2048 <= parsed.key.key_size <= 4096:
                    raise ValueError("RSA keys require 2048 to 4096 bits")
            except (jwt.PyJWTError, ValueError, TypeError, KeyError):
                raise ValueError("The public verification key is invalid") from None
        identities = [(item.subject, item.client_id) for item in self.mappings]
        if len(set(identities)) != len(identities):
            raise ValueError("OAuth subject/client mappings must be unambiguous")
        return self


_PRIVATE_PROXY_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


class CloudIngressProfile(TypedModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal[1] = 1
    deployment_id: Handle
    realm: Handle
    public_origin: str
    auth_mode: Literal["bearer", "oauth"]
    tls_proxy: Literal["none", "loopback", "private"] = "none"
    trusted_proxy_ip: str | None = Field(default=None, min_length=7, max_length=15)
    oauth: OAuthResourceProfile | None = None

    @field_validator("public_origin")
    @classmethod
    def public_https_root(cls, value: str) -> str:
        try:
            return https_origin(value)
        except DomainError:
            raise ValueError("The public origin requires a canonical HTTPS root") from None

    @model_validator(mode="after")
    def explicit_authentication(self) -> CloudIngressProfile:
        if (self.auth_mode == "oauth") != (self.oauth is not None):
            raise ValueError("Only OAuth ingress requires an issuer, public keys and identity mappings")
        if self.oauth is not None and self.oauth.audience != self.public_origin:
            raise ValueError("The OAuth resource audience must equal the configured public origin")
        if self.tls_proxy == "private":
            if self.trusted_proxy_ip is None:
                raise ValueError("A private TLS proxy requires its exact private IPv4 address")
            address = ipaddress.IPv4Address(self.trusted_proxy_ip)
            if str(address) != self.trusted_proxy_ip or not any(address in network for network in _PRIVATE_PROXY_NETWORKS):
                raise ValueError("The TLS proxy must have one canonical RFC1918 IPv4 address")
        elif self.trusted_proxy_ip is not None:
            raise ValueError("A proxy address applies only to private TLS proxy ingress")
        return self


    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("The ingress profile version must be an integer")
        return value


def _profile_for(settings: Settings, profile: CloudIngressProfile) -> CloudIngressProfile:
    if (profile.deployment_id, profile.realm) != (settings.deployment_id, settings.realm):
        raise DomainError("INGRESS_IDENTITY_DENIED", "The ingress profile belongs to another deployment or realm", status=503)
    return profile


def _cloud_directory(settings: Settings, *, create: bool = False) -> Path:
    state = settings.state_dir
    cloud = state / "cloud"
    if create:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in (state, cloud):
        if create and directory == cloud:
            cloud.mkdir(exist_ok=True, mode=0o700)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("INGRESS_CONFIG_INVALID", "Ingress configuration requires private owned directories", status=503)
    return cloud


def load_ingress(settings: Settings) -> CloudIngressProfile | None:
    path = settings.state_dir / "cloud" / "ingress.json"
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    try:
        _cloud_directory(settings)
        return _profile_for(settings, validate_wire(CloudIngressProfile, decode_json(private_read(path, INGRESS_MAX_BYTES))))
    except (OSError, ValueError, TypeError, DomainError):
        raise DomainError("INGRESS_CONFIG_INVALID", "The private ingress profile is invalid", status=503) from None


def configure_ingress(settings: Settings, profile: CloudIngressProfile) -> Path:
    profile = _profile_for(settings, CloudIngressProfile.model_validate_json(profile.model_dump_json()))
    raw = profile.model_dump_json(indent=2) + "\n"
    if len(raw.encode()) > INGRESS_MAX_BYTES:
        raise DomainError("INGRESS_CONFIG_INVALID", "The ingress profile exceeds its bound")
    path = _cloud_directory(settings, create=True) / "ingress.json"
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private_write(path, raw, replace=True, directory=directory)
    finally:
        os.close(directory)
    return path


def public_request(profile: CloudIngressProfile | None, settings: Settings, scope: dict, headers: dict[bytes, bytes]) -> bool:
    forwarded = {key for key in headers if key == b"forwarded" or key.startswith(b"x-forwarded-") or key in {b"x-real-ip", b"x-original-host", b"x-original-proto"}}
    if forwarded - {b"x-forwarded-proto"}:
        raise DomainError("HEADERS_INVALID", "Forwarded security headers are not permitted", status=400)
    host = headers.get(b"host")
    peer = scope.get("client")
    try:
        address = ipaddress.ip_address(peer[0]) if peer else None
    except ValueError:
        address = None
    local_hosts = {f"127.0.0.1:{settings.port}".encode(), f"localhost:{settings.port}".encode()}
    if host in local_hosts:
        if address is None or not address.is_loopback:
            raise DomainError("HOST_ORIGIN_DENIED", "Local authority requests require a loopback peer", status=403)
        if forwarded:
            raise DomainError("HEADERS_INVALID", "Local requests cannot use forwarded security headers", status=400)
        if b"origin" in headers and headers[b"origin"] not in {b"http://" + item for item in local_hosts}:
            raise DomainError("HOST_ORIGIN_DENIED", "Host or Origin is not permitted", status=403)
        return False
    if profile is None or host != urlsplit(profile.public_origin).netloc.encode():
        raise DomainError("HOST_ORIGIN_DENIED", "Host or Origin is not permitted", status=403)
    if b"origin" in headers and headers[b"origin"] != profile.public_origin.encode():
        raise DomainError("HOST_ORIGIN_DENIED", "Host or Origin is not permitted", status=403)
    if scope.get("scheme") == "https" and not forwarded:
        return True
    declared_proxy = (
        profile.tls_proxy == "loopback" and address is not None and address.is_loopback
        or profile.tls_proxy == "private" and str(address) == profile.trusted_proxy_ip
    )
    if declared_proxy and scope.get("scheme") == "http" and headers.get(b"x-forwarded-proto") == b"https":
        return True
    raise DomainError("TLS_REQUIRED", "The public origin requires HTTPS or its explicitly declared TLS proxy", status=403)


@dataclass(frozen=True)
class VerifiedOAuthIdentity:
    issuer: str
    subject: str
    client_id: str
    credential_id: str
    generation: int
    scopes: tuple[str, ...]
    expires_at: int

    def access_token(self, token: str, resource: str) -> AccessToken:
        return AccessToken(token=token, client_id=self.client_id, scopes=list(self.scopes),
                           expires_at=self.expires_at, resource=resource, subject=self.subject,
                           claims={"iss": self.issuer})


class OAuthVerifier:
    def __init__(self, profile: OAuthResourceProfile, store) -> None:
        self.profile = profile
        self.store = store
        self.keys = {item["kid"]: jwt.PyJWK.from_dict(item, algorithm=item["alg"]) for item in profile.jwks["keys"]}

    async def authenticate(self, token: str) -> tuple[Principal, VerifiedOAuthIdentity]:
        denied = DomainError("AUTH_DENIED", "A valid mapped OAuth access token is required", status=401)
        try:
            if not token.isascii() or len(token) > 16384 or token.count(".") != 2:
                raise denied
            parts = token.split(".")
            header = decode_json(jwt.utils.base64url_decode(parts[0]))
            claims = decode_json(jwt.utils.base64url_decode(parts[1]))
            if (not isinstance(header, dict) or set(header) - {"alg", "typ", "kid"}
                    or header.get("typ") not in {"at+jwt", "application/at+jwt"}
                    or header.get("alg") not in self.profile.algorithms
                    or not isinstance(header.get("kid"), str)):
                raise denied
            key = self.keys.get(header["kid"])
            if key is None or key.algorithm_name != header["alg"]:
                raise denied
            if not isinstance(claims, dict):
                raise denied
            for name, maximum in (("iss", 2048), ("sub", 512), ("client_id", 256), ("jti", 512), ("scope", 2048)):
                if not isinstance(claims.get(name), str) or not 1 <= len(claims[name]) <= maximum:
                    raise denied
            if (any(type(claims.get(name)) is not int for name in ("exp", "iat"))
                    or ("nbf" in claims and type(claims["nbf"]) is not int)
                    or not 0 < claims["exp"] - claims["iat"] <= 3600
                    or claims["iat"] > time.time() or claims["aud"] != self.profile.audience
                    or claims["iss"] != self.profile.issuer):
                raise denied
            jwt.decode(token, key.key, algorithms=[header["alg"]], issuer=self.profile.issuer,
                       audience=self.profile.audience, options={"require": ["iss", "sub", "aud", "exp", "iat", "jti", "client_id"], "strict_aud": True})
            scopes = tuple(claims["scope"].split(" "))
            if len(scopes) > 32 or len(set(scopes)) != len(scopes) or any(
                not scope or any(ord(c) < 33 or ord(c) > 126 or c in '\\"' for c in scope) for scope in scopes
            ):
                raise denied
            matches = [item for item in self.profile.mappings if item.subject == claims["sub"] and item.client_id == claims["client_id"]]
            if len(matches) != 1 or not set(matches[0].required_scopes).issubset(scopes):
                raise denied
            mapping = matches[0]
            actor = await self.store.authenticate_external(mapping.credential_id, mapping.generation)
            return actor, VerifiedOAuthIdentity(self.profile.issuer, claims["sub"], claims["client_id"],
                                                mapping.credential_id, mapping.generation, scopes, claims["exp"])
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError):
            raise denied from None

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            _, identity = await self.authenticate(token)
            return identity.access_token(token, self.profile.audience)
        except DomainError:
            return None


class ClientBootstrapRequest(TypedModel):
    binding_id: Handle


class ClientBootstrapBounds(TypedModel):
    max_capture_bytes: int = Field(ge=1024, le=1048576)
    max_http_body_bytes: int = Field(ge=16384, le=262144)
    max_mcp_response_bytes: int = Field(ge=4096, le=65536)
    spool_limit_bytes: int = Field(ge=65536, le=1073741824)
    max_concurrent_requests: int = Field(ge=1, le=256)


class ClientBootstrapResult(TypedModel):
    version: Literal[1] = 1
    deployment_id: Handle
    realm: Handle
    mode: Literal["personal", "company"]
    capability: Literal["agent_judged"]
    auth_mode: Literal["bearer", "oauth"]
    credential_id: Handle
    generation: int = Field(ge=1)
    role: Literal["agent", "producer"]
    bindings: tuple[Handle, ...] = Field(min_length=1, max_length=1)
    binding_id: Handle
    binding_revision: int = Field(ge=1)
    bounds: ClientBootstrapBounds

    @model_validator(mode="after")
    def exact_binding(self) -> ClientBootstrapResult:
        if self.bindings != (self.binding_id,):
            raise ValueError("Bootstrap requires exactly the requested binding")
        return self
