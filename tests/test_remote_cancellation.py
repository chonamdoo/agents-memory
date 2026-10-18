from __future__ import annotations

import asyncio
import errno
import json
import socket
import ssl
import subprocess
import threading
import time
from contextlib import suppress
from types import SimpleNamespace

import pytest
from test_remote_client import capture
from test_remote_client import tls_endpoint as tls_endpoint

from agents_memory import client as client_module
from agents_memory import connection
from agents_memory.client import LocalClient
from agents_memory.domain import DomainError, EffectState
from agents_memory.readiness import ensure_remote_ready


def remote_request(endpoint, stopped):
    profile = endpoint.profile
    client = LocalClient(profile.base_url, endpoint.token, timeout=20,
                         state_dir=profile.state_dir, deployment_id=profile.deployment_id,
                         remote_settings=profile)
    with connection.remote_connection_cycle(profile, deadline=time.monotonic() + 20, stop_event=stopped):
        return client.request("/api/capture", capture())


@pytest.mark.parametrize("stage", ["headers", "body"])
async def test_readonly_ready_stop_cancels_real_tls_response_before_business_dispatch(tls_endpoint, stage):
    stopped, started, release = threading.Event(), threading.Event(), threading.Event()
    tls_endpoint.state.update(ready_pause=stage, ready_started=started, ready_release=release)
    task = asyncio.create_task(asyncio.to_thread(
        ensure_remote_ready, tls_endpoint.profile, timeout=20, stop_event=stopped,
    ))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        stopped.set()
        with pytest.raises(DomainError) as denied:
            await asyncio.wait_for(asyncio.shield(task), 1)
        assert denied.value.code == "SERVICE_DRAINING"
        assert denied.value.effect is EffectState.NOT_STARTED
        assert tls_endpoint.state["posts"] == []
    finally:
        release.set()
        with suppress(DomainError):
            await asyncio.wait_for(task, 6)


def test_stop_between_verified_connect_and_first_send_never_posts(tls_endpoint, monkeypatch):
    stopped = threading.Event()
    connect = connection._DeadlineHTTPSConnection.connect

    def stop_after_connect(self):
        connect(self)
        if tls_endpoint.state["gets"]:
            stopped.set()

    monkeypatch.setattr(connection._DeadlineHTTPSConnection, "connect", stop_after_connect)
    with pytest.raises(DomainError) as denied:
        remote_request(tls_endpoint, stopped)
    assert denied.value.code == "SERVICE_DRAINING"
    assert denied.value.effect is EffectState.NOT_STARTED
    assert tls_endpoint.state["posts"] == []
    assert len(tls_endpoint.state["gets"]) == 1


async def test_already_dispatched_business_request_drains_response_without_retry(tls_endpoint):
    stopped, started, release = threading.Event(), threading.Event(), threading.Event()
    tls_endpoint.state.update(post_received=started, post_release=release)
    task = asyncio.create_task(asyncio.to_thread(remote_request, tls_endpoint, stopped))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        stopped.set()
        release.set()
        result = await asyncio.wait_for(asyncio.shield(task), 2)
        assert result == {"effect": "committed", "id": "operation-one"}
        assert [(route, body) for route, body, _ in tls_endpoint.state["posts"]] == [
            ("/api/capture", capture()),
        ]
    finally:
        release.set()
        with suppress(DomainError):
            await asyncio.wait_for(task, 6)


async def test_pending_tcp_connect_is_interruptible_and_closes_socket(monkeypatch):
    pending, peer = socket.socketpair()
    pending.setblocking(False)
    try:
        while True:
            pending.send(b"x" * 65536)
    except BlockingIOError:
        pass
    started, stopped = threading.Event(), threading.Event()

    class PendingConnect:
        def __getattr__(self, name):
            return getattr(pending, name)

        def connect_ex(self, target):
            started.set()
            return errno.EINPROGRESS

    monkeypatch.setattr(connection, "_resolve_tcp", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 9)),
    ])
    monkeypatch.setattr(connection, "socket", SimpleNamespace(
        socket=lambda *args: PendingConnect(), SOL_SOCKET=socket.SOL_SOCKET, SO_ERROR=socket.SO_ERROR,
    ))
    task = asyncio.create_task(asyncio.to_thread(
        connection._connect_tcp, ("localhost", 9), time.monotonic() + 20, stop_event=stopped,
    ))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        stopped.set()
        with pytest.raises(DomainError) as denied:
            await asyncio.wait_for(asyncio.shield(task), 1)
        assert denied.value.code == "SERVICE_DRAINING"
        assert denied.value.effect is EffectState.NOT_STARTED
        assert pending.fileno() == -1
    finally:
        stopped.set()
        pending.close()
        peer.close()
        with suppress(DomainError, OSError):
            await asyncio.wait_for(task, 6)


async def test_stop_during_real_business_tls_handshake_never_posts(tls_endpoint, monkeypatch):
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    observed = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls_endpoint.profile.ca_bundle, tls_endpoint.server_key)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)

    def serve():
        try:
            raw, _ = listener.accept()
            with raw:
                raw.settimeout(5)
                if raw.recv(1, socket.MSG_PEEK):
                    started.set()
                release.wait(5)
                with context.wrap_socket(raw, server_side=True) as secured:
                    request = secured.recv(65536)
                    observed.append(request)
                    body = json.dumps({"effect": "committed", "id": "operation-one"}).encode()
                    secured.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode()
                                    + b"\r\n\r\n" + body)
        except OSError:
            pass

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    original_profile = tls_endpoint.profile
    profile = original_profile.model_copy(update={"base_url": f"https://localhost:{listener.getsockname()[1]}"})
    target = SimpleNamespace(profile=profile, token=tls_endpoint.token)
    monkeypatch.setattr(client_module, "ensure_remote_ready", lambda *args, **kwargs:
                        ensure_remote_ready(original_profile, timeout=kwargs["timeout"]))
    task = asyncio.create_task(asyncio.to_thread(remote_request, target, stopped))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        stopped.set()
        with pytest.raises(DomainError) as denied:
            await asyncio.wait_for(asyncio.shield(task), 1)
        assert denied.value.code == "SERVICE_DRAINING"
        assert denied.value.effect is EffectState.NOT_STARTED
    finally:
        stopped.set()
        release.set()
        with suppress(DomainError):
            await asyncio.wait_for(task, 6)
        listener.close()
        await asyncio.to_thread(server.join, 6)
    assert not server.is_alive()
    assert observed == []
    assert tls_endpoint.state["posts"] == []


def test_stoppable_readiness_completes_real_slow_dns_helper_and_reaps_it(tls_endpoint, monkeypatch):
    processes = []
    spawn = subprocess.Popen

    def slow_resolution(argv, **kwargs):
        command = list(argv)
        position = command.index("-c") + 1
        command[position] = "import time; time.sleep(0.75); " + command[position]
        process = spawn(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(connection.subprocess, "Popen", slow_resolution)
    result = ensure_remote_ready(tls_endpoint.profile, timeout=3, stop_event=threading.Event())
    assert result["ready"] is True and result["db_ready"] is True
    assert len(tls_endpoint.state["gets"]) == 1
    assert tls_endpoint.state["posts"] == []
    assert len(processes) == 1 and processes[0].poll() == 0
