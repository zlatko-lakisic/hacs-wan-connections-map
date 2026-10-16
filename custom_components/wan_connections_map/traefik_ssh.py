"""Read the Traefik access log over SSH."""

from __future__ import annotations

from pathlib import Path
import shlex

import paramiko


def read_access_log(
    host: str,
    username: str,
    password: str,
    path: str,
    *,
    port: int = 22,
    known_hosts: Path | None = None,
) -> str:
    """Return the tail of the remote access log."""
    client = paramiko.SSHClient()
    if known_hosts and known_hosts.is_file():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port or 22,
        username=username,
        password=password,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        if known_hosts:
            known_hosts.parent.mkdir(parents=True, exist_ok=True)
            client.save_host_keys(str(known_hosts))
        command = f"tail -c 524288 {shlex.quote(path)}"
        _stdin, stdout, stderr = client.exec_command(command, timeout=20)
        payload = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace").strip()
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise OSError(error or f"tail exited {code}")
        return payload
    finally:
        client.close()
