#!/usr/bin/env python3
"""
Query a Minecraft server status endpoint and write Prometheus textfile metrics.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import tempfile
import time
from pathlib import Path


def encode_varint(value: int) -> bytes:
    out = bytearray()
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_varint(sock: socket.socket) -> int:
    value = 0
    shift = 0
    for _ in range(5):
        raw = sock.recv(1)
        if not raw:
            raise EOFError("socket closed while reading varint")
        byte = raw[0]
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value
        shift += 7
    raise ValueError("varint too long")


def read_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise EOFError("socket closed while reading packet")
        chunks.extend(chunk)
    return bytes(chunks)


def packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = encode_varint(packet_id) + payload
    return encode_varint(len(body)) + body


def encode_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return encode_varint(len(raw)) + raw


def query_status(host: str, port: int, timeout: float) -> tuple[dict, float]:
    started = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)

        handshake = (
            encode_varint(765)
            + encode_string(host)
            + struct.pack(">H", port)
            + encode_varint(1)
        )
        sock.sendall(packet(0, handshake))
        sock.sendall(packet(0))

        _length = read_varint(sock)
        packet_id = read_varint(sock)
        if packet_id != 0:
            raise ValueError(f"unexpected status packet id {packet_id}")
        response_len = read_varint(sock)
        response = json.loads(read_exact(sock, response_len).decode("utf-8"))

        payload = struct.pack(">q", int(time.time() * 1000))
        ping_started = time.monotonic()
        sock.sendall(packet(1, payload))
        _pong_length = read_varint(sock)
        pong_id = read_varint(sock)
        if pong_id != 1:
            raise ValueError(f"unexpected pong packet id {pong_id}")
        _pong_payload = read_exact(sock, 8)
        latency = time.monotonic() - ping_started

    total_latency = time.monotonic() - started
    return response, latency if latency > 0 else total_latency


def label_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric(name: str, value: object, server: str) -> str:
    return f'{name}{{server="{label_escape(server)}"}} {value}'


def render_metrics(args: argparse.Namespace) -> str:
    lines = [
        "# HELP tresor_minecraft_up Whether the Minecraft status query succeeded.",
        "# TYPE tresor_minecraft_up gauge",
        "# HELP tresor_minecraft_players_online Current online player count from server status.",
        "# TYPE tresor_minecraft_players_online gauge",
        "# HELP tresor_minecraft_players_max Maximum player count from server status.",
        "# TYPE tresor_minecraft_players_max gauge",
        "# HELP tresor_minecraft_ping_latency_seconds Minecraft status ping latency in seconds.",
        "# TYPE tresor_minecraft_ping_latency_seconds gauge",
        "# HELP tresor_minecraft_protocol_version Minecraft protocol version reported by the server.",
        "# TYPE tresor_minecraft_protocol_version gauge",
        "# HELP tresor_minecraft_last_scrape_timestamp_seconds Unix timestamp of the latest textfile scrape attempt.",
        "# TYPE tresor_minecraft_last_scrape_timestamp_seconds gauge",
    ]

    now = int(time.time())
    try:
        status, latency = query_status(args.host, args.port, args.timeout)
        players = status.get("players") or {}
        version = status.get("version") or {}
        lines.extend(
            [
                metric("tresor_minecraft_up", 1, args.server_label),
                metric("tresor_minecraft_players_online", int(players.get("online", 0)), args.server_label),
                metric("tresor_minecraft_players_max", int(players.get("max", 0)), args.server_label),
                metric("tresor_minecraft_ping_latency_seconds", f"{latency:.6f}", args.server_label),
                metric("tresor_minecraft_protocol_version", int(version.get("protocol", 0)), args.server_label),
                metric("tresor_minecraft_last_scrape_timestamp_seconds", now, args.server_label),
            ]
        )
    except Exception:
        lines.extend(
            [
                metric("tresor_minecraft_up", 0, args.server_label),
                metric("tresor_minecraft_last_scrape_timestamp_seconds", now, args.server_label),
            ]
        )

    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=25565)
    parser.add_argument("--server-label", default="tresor_mc")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    atomic_write(Path(args.output), render_metrics(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
