#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remote active probe for Hysteria2 masquerade behavior.

This does not reproduce the real GFW. It sends simple remote UDP and HTTP/3
probes that resemble unauthenticated active checks and reports whether the
server exposes a plausible masquerade page.
"""

import argparse
import asyncio
import dataclasses
import socket
import ssl
import sys
from typing import Dict, List, Optional

try:
    from aioquic.asyncio.client import connect
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.h3.connection import H3_ALPN, H3Connection
    from aioquic.h3.events import DataReceived, HeadersReceived
    from aioquic.quic.configuration import QuicConfiguration
except ImportError:
    connect = None
    QuicConnectionProtocol = object
    H3_ALPN = None
    H3Connection = None
    DataReceived = None
    HeadersReceived = None
    QuicConfiguration = None


@dataclasses.dataclass
class Http3ProbeResult:
    ok: bool
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None
    body: str = ""
    error: str = ""
    path: str = "/"


@dataclasses.dataclass
class Classification:
    level: str
    message: str


class H3ProbeProtocol(QuicConnectionProtocol):
    def __init__(self, quic, stream_handler=None):
        super().__init__(quic, stream_handler=stream_handler)
        self._h3 = H3Connection(quic)
        self._response_waiter = None
        self._response_stream_id = None
        self._response_headers: Dict[str, str] = {}
        self._response_body: List[bytes] = []

    async def get(self, path: str, authority: str, timeout: float) -> Http3ProbeResult:
        stream_id = self._quic.get_next_available_stream_id()
        self._response_stream_id = stream_id
        self._response_waiter = asyncio.get_event_loop().create_future()
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"GET"),
                (b":scheme", b"https"),
                (b":authority", authority.encode()),
                (b":path", path.encode()),
                (b"user-agent", b"Mozilla/5.0 active-probe"),
            ],
            end_stream=True,
        )
        self.transmit()
        try:
            return await asyncio.wait_for(self._response_waiter, timeout=timeout)
        except asyncio.TimeoutError:
            return _build_http3_result(path, self._response_headers, self._response_body)

    def quic_event_received(self, event):
        for h3_event in self._h3.handle_event(event):
            if isinstance(h3_event, HeadersReceived) and h3_event.stream_id == self._response_stream_id:
                for key, value in h3_event.headers:
                    self._response_headers[key.decode(errors="ignore").lower()] = value.decode(errors="ignore")
            elif isinstance(h3_event, DataReceived) and h3_event.stream_id == self._response_stream_id:
                self._response_body.append(h3_event.data)
                if h3_event.stream_ended and self._response_waiter and not self._response_waiter.done():
                    self._response_waiter.set_result(
                        _build_http3_result("", self._response_headers, self._response_body)
                    )


def verify_udp_port(host: str, port: int, timeout: float) -> Classification:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(b"\x00", (host, port))
        try:
            sock.recvfrom(4096)
            return Classification("PASS", "UDP port replied to a probe packet")
        except socket.timeout:
            return Classification("WARN", "UDP packet sent; no reply is common for invalid QUIC packets")
    except OSError as exc:
        return Classification("FAIL", "UDP probe failed: {}".format(exc))
    finally:
        sock.close()


async def probe_http3(host: str, port: int, sni: str, path: str, timeout: float) -> Http3ProbeResult:
    if connect is None:
        return Http3ProbeResult(
            ok=False,
            error="missing dependency: install aioquic with 'python3 -m pip install aioquic'",
            path=path,
        )

    try:
        return await asyncio.wait_for(_probe_http3_once(host, port, sni, path, timeout), timeout=timeout + 1)
    except asyncio.TimeoutError:
        return Http3ProbeResult(ok=False, error="timed out waiting for QUIC/HTTP3 response", path=path)


async def _probe_http3_once(host: str, port: int, sni: str, path: str, timeout: float) -> Http3ProbeResult:

    configuration = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    configuration.server_name = sni
    configuration.verify_mode = ssl.CERT_NONE

    try:
        async with connect(
            host,
            port,
            configuration=configuration,
            create_protocol=H3ProbeProtocol,
            wait_connected=True,
        ) as client:
            result = await client.get(path, sni, timeout)
            result.path = path
            return result
    except Exception as exc:
        return Http3ProbeResult(ok=False, error=str(exc), path=path)


def _build_http3_result(path: str, headers: Dict[str, str], body_parts: List[bytes]) -> Http3ProbeResult:
    status = headers.get(":status")
    status_code = int(status) if status and status.isdigit() else None
    body = b"".join(body_parts).decode("utf-8", errors="replace")
    return Http3ProbeResult(ok=True, status_code=status_code, headers=headers, body=body, path=path)


def classify_http3_response(result: Http3ProbeResult) -> Classification:
    if not result.ok:
        return Classification("FAIL", "HTTP/3 probe failed: {}".format(result.error or "unknown error"))

    body = result.body.lower()
    if not body.strip():
        return Classification("WARN", "HTTP/3 responded but body was empty")

    markers = [
        ("API documentation page", ["api documentation", "api reference", "endpoint"]),
        ("nginx default page", ["welcome to nginx"]),
        ("404 masquerade page", ["404 not found", "not found"]),
        ("company page", ["solutions", "enterprise", "platform"]),
        ("blog page", ["blog", "article", "posted"]),
    ]
    for label, words in markers:
        if any(word in body for word in words):
            return Classification("PASS", "HTTP/3 returned a plausible {}".format(label))

    if result.status_code and 200 <= result.status_code < 500:
        return Classification(
            "WARN",
            "HTTP/3 returned status {}, but no known template marker was found".format(result.status_code),
        )
    return Classification("FAIL", "HTTP/3 returned no usable masquerade page")


async def run_probes(args) -> int:
    asyncio.get_event_loop().set_exception_handler(_quiet_connection_errors)
    print("== GFW-like remote active probe ==")
    print("target: {}:{}  sni: {}".format(args.host, args.port, args.sni))
    print()

    udp = verify_udp_port(args.host, args.port, args.timeout)
    print("[UDP] {}: {}".format(udp.level, udp.message))

    final_level = "FAIL"
    for path in args.path:
        result = await probe_http3(args.host, args.port, args.sni, path, args.timeout)
        classification = classify_http3_response(result)
        final_level = _max_level(final_level, classification.level)
        print()
        print("[HTTP/3 {}] {}: {}".format(path, classification.level, classification.message))
        if result.status_code is not None:
            print("  status: {}".format(result.status_code))
        if result.headers:
            content_type = result.headers.get("content-type", "")
            if content_type:
                print("  content-type: {}".format(content_type))
        if result.body:
            snippet = " ".join(result.body.split())[:220]
            print("  body: {}".format(snippet))

    print()
    if final_level == "PASS":
        print("RESULT: PASS - remote probes saw a masquerade response")
        return 0
    if final_level == "WARN":
        print("RESULT: WARN - server responded, but masquerade was not confirmed")
        return 2
    print("RESULT: FAIL - masquerade was not observed")
    return 1


def _max_level(current: str, candidate: str) -> str:
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    return candidate if order[candidate] > order[current] else current


def _quiet_connection_errors(loop, context):
    exc = context.get("exception")
    if isinstance(exc, ConnectionError):
        return
    loop.default_exception_handler(context)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Probe Hysteria2 masquerade from a remote machine")
    parser.add_argument("host", help="server IP or domain")
    parser.add_argument("port", type=int, help="server UDP port")
    parser.add_argument("--sni", default="bing.com", help="TLS SNI / HTTP authority")
    parser.add_argument("--timeout", type=float, default=5.0, help="probe timeout in seconds")
    parser.add_argument(
        "--path",
        action="append",
        default=["/", "/robots.txt", "/__gfw_probe_404__"],
        help="HTTP/3 path to probe; can be repeated",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    return asyncio.run(run_probes(args))


if __name__ == "__main__":
    sys.exit(main())
