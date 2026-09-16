from __future__ import annotations

import argparse
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


MAX_HEADER_BYTES = 64 * 1024
ALLOWED_PORTS = {80, 443}
BLOCKED_NAMES = {"localhost", "host.docker.internal", "gateway.docker.internal"}


class ProxyDenied(RuntimeError):
    pass


def hostname_allowed(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if not host or host in BLOCKED_NAMES or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global


async def resolve_public(hostname: str, port: int) -> tuple[str, int]:
    if port not in ALLOWED_PORTS or not hostname_allowed(hostname):
        raise ProxyDenied("destination denied")
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        hostname,
        port,
        family=socket.AF_UNSPEC,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    public: list[tuple[str, int]] = []
    for _family, _type, _proto, _canonname, sockaddr in records:
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global:
            raise ProxyDenied("destination resolved to a non-public address")
        public.append((sockaddr[0], int(sockaddr[1])))
    if not public:
        raise ProxyDenied("destination did not resolve")
    return public[0]


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(64 * 1024):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (ConnectionError, RuntimeError):
            pass


async def read_headers(reader: asyncio.StreamReader) -> bytes:
    data = await reader.readuntil(b"\r\n\r\n")
    if len(data) > MAX_HEADER_BYTES:
        raise ProxyDenied("headers too large")
    return data


def parse_authority(value: str, default_port: int) -> tuple[str, int]:
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            raise ProxyDenied("invalid IPv6 authority")
        host = value[1:end]
        suffix = value[end + 1 :]
        port = int(suffix[1:]) if suffix.startswith(":") else default_port
        return host, port
    host, separator, port_text = value.rpartition(":")
    if separator and port_text.isdigit():
        return host, int(port_text)
    return value, default_port


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        headers = await read_headers(reader)
        first_line, *header_lines = headers.split(b"\r\n")
        method_raw, target_raw, version = first_line.split(b" ", 2)
        method = method_raw.decode("ascii", "strict").upper()
        target = target_raw.decode("ascii", "strict")

        if method == "CONNECT":
            hostname, port = parse_authority(target, 443)
            address, resolved_port = await resolve_public(hostname, port)
            upstream_reader, upstream_writer = await asyncio.open_connection(address, resolved_port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\nConnection: keep-alive\r\n\r\n")
            await writer.drain()
        else:
            parsed = urlsplit(target)
            if parsed.scheme.lower() != "http" or not parsed.hostname:
                raise ProxyDenied("only HTTP absolute-form requests and HTTPS CONNECT are supported")
            port = parsed.port or 80
            address, resolved_port = await resolve_public(parsed.hostname, port)
            upstream_reader, upstream_writer = await asyncio.open_connection(address, resolved_port)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            filtered = [line for line in header_lines if not line.lower().startswith(b"proxy-")]
            rewritten = b" ".join((method_raw, path.encode("ascii"), version)) + b"\r\n"
            upstream_writer.write(rewritten + b"\r\n".join(filtered) + b"\r\n")
            await upstream_writer.drain()

        await asyncio.gather(
            pipe(reader, upstream_writer),
            pipe(upstream_reader, writer),
        )
    except (ProxyDenied, ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        try:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except ConnectionError:
            pass
    except (OSError, ConnectionError):
        try:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            await writer.drain()
        except ConnectionError:
            pass
    finally:
        if upstream_writer and not upstream_writer.is_closing():
            upstream_writer.close()
        if not writer.is_closing():
            writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def serve(host: str, port: int) -> None:
    server = await asyncio.start_server(handle_client, host, port, limit=MAX_HEADER_BYTES)
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()
