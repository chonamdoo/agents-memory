from __future__ import annotations

import asyncio
import json
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.request

import pytest
from test_store_authority import authority as authority

from agents_memory.config import Settings
from agents_memory.private_io import private_write


def test_occupied_listen_address_refuses_before_database_or_journal_work(tmp_path):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        settings = Settings(
            deployment_id="bind-refusal", realm="personal", mode="personal",
            database_dsn="postgresql://127.0.0.1:1/unreachable",
            state_dir=tmp_path / "state", journal_dir=tmp_path / "journal",
            port=occupied.getsockname()[1],
        )
        config = tmp_path / "config.json"
        private_write(config, settings.model_dump_json())
        refused = subprocess.run(
            [sys.executable, "-I", "-m", "agents_memory.cli", "--config", str(config), "serve"],
            cwd=tmp_path, capture_output=True, timeout=10,
        )
        assert refused.returncode == 1
        error = json.loads(refused.stderr)["error"]
        assert error["code"] == "SERVICE_BIND_FAILED" and error["effect"] == "not_started"
        assert not settings.journal_dir.exists()
        assert not settings.state_dir.exists()
        assert occupied.getsockname()[1] == settings.port


@pytest.mark.parametrize("shutdown_signal", [signal.SIGTERM, signal.SIGINT])
async def test_prebound_cli_serves_actual_database_readiness_and_releases_listener(authority, tmp_path, shutdown_signal):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    settings = authority.store.settings.model_copy(update={"port": port})
    config = tmp_path / "served.json"
    private_write(config, settings.model_dump_json())
    process = subprocess.Popen(
        [sys.executable, "-I", "-m", "agents_memory.cli", "--config", str(config), "serve"],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def readiness():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=0.2) as response:
            return json.load(response)

    try:
        async with asyncio.timeout(10):
            while True:
                assert process.poll() is None
                try:
                    result = await asyncio.to_thread(readiness)
                except (OSError, ValueError, urllib.error.URLError):
                    await asyncio.sleep(0.02)
                    continue
                if result.get("ready") is True:
                    break
        assert result["db_ready"] is True
        assert result["deployment_id"] == settings.deployment_id
        assert result["realm"] == settings.realm
    finally:
        if process.poll() is None:
            process.send_signal(shutdown_signal)
        try:
            _, stderr = await asyncio.to_thread(process.communicate, timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = await asyncio.to_thread(process.communicate, timeout=5)
    with socket.socket() as released:
        released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        released.bind(("127.0.0.1", port))
    if shutdown_signal == signal.SIGINT:
        assert process.returncode == 130
        assert b"Traceback" not in stderr
        error = json.loads(stderr.decode().splitlines()[-1])["error"]
        assert error["code"] == "COMMAND_INTERRUPTED" and error["effect"] == "unknown"
