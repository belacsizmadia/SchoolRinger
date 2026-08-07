#!/usr/bin/env python3
"""Play a local MP3 file on a Google Cast speaker group."""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, unquote, urlsplit

import pychromecast
from pychromecast.const import CAST_TYPE_GROUP


class QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    """Serve the media file without printing every range request."""

    def __init__(self, *args: object, allowed_name: str, **kwargs: object) -> None:
        self.allowed_name = allowed_name
        super().__init__(*args, **kwargs)

    def _is_allowed(self) -> bool:
        requested_name = unquote(urlsplit(self.path).path).lstrip("/")
        return requested_name == self.allowed_name

    def do_GET(self) -> None:
        if not self._is_allowed():
            self.send_error(http.HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if not self._is_allowed():
            self.send_error(http.HTTPStatus.NOT_FOUND)
            return
        super().do_HEAD()

    def log_message(self, format: str, *args: object) -> None:
        return


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Helyi MP3 lejátszása Google Home speaker groupon."
    )
    parser.add_argument("--file", type=Path, default=Path("teszt.mp3"))
    parser.add_argument("--group", help="A Google Home speaker group pontos neve")
    parser.add_argument("--host-ip", help="A hangszórók által elérhető helyi IP-cím")
    parser.add_argument("--port", type=int, default=0, help="HTTP port (0: automatikus)")
    parser.add_argument("--timeout", type=float, default=12.0, help="Felderítés ideje")
    parser.add_argument("--list", action="store_true", help="Csak a csoportok listázása")
    return parser.parse_args(argv)


def discover_groups(timeout: float) -> tuple[list[Any], Any]:
    devices, browser = pychromecast.discovery.discover_chromecasts(timeout=timeout)
    casts = [
        pychromecast.get_chromecast_from_cast_info(device, browser.zc)
        for device in devices
    ]
    groups = [cast for cast in casts if cast.cast_type == CAST_TYPE_GROUP]
    return sorted(groups, key=lambda cast: (cast.name or "").casefold()), browser


def choose_group(groups: Sequence[Any], requested_name: str | None) -> Any:
    if not groups:
        raise RuntimeError("Nem található Google Cast speaker group a hálózaton.")

    if requested_name:
        matches = [group for group in groups if group.name == requested_name]
        if not matches:
            names = ", ".join(group.name or "<névtelen>" for group in groups)
            raise RuntimeError(
                f"Nincs ilyen speaker group: {requested_name!r}. Elérhető: {names}"
            )
        return matches[0]

    print("Elérhető speaker groupok:")
    for index, group in enumerate(groups, start=1):
        print(f"  {index}. {group.name}")

    while True:
        try:
            selected = int(input("Válassz sorszámot: "))
            return groups[selected - 1]
        except (ValueError, IndexError):
            print("Érvénytelen sorszám.", file=sys.stderr)


def local_ip_for(remote_host: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((remote_host, 8009))
        return str(probe.getsockname()[0])


def start_media_server(file_path: Path, port: int) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(
        QuietFileHandler,
        directory=str(file_path.parent),
        allowed_name=file_path.name,
    )
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def play(group: Any, file_path: Path, host_ip: str | None, port: int) -> None:
    group.wait(timeout=10)
    advertised_ip = host_ip or local_ip_for(group.cast_info.host)
    server = start_media_server(file_path, port)
    media_url = f"http://{advertised_ip}:{server.server_port}/{quote(file_path.name)}"

    print(f"Csoport: {group.name}")
    print(f"Média URL: {media_url}")
    print("Lejátszás indítása...")

    controller = group.media_controller
    try:
        controller.play_media(
            media_url,
            "audio/mpeg",
            title=file_path.stem,
            stream_type="BUFFERED",
        )
        controller.block_until_active(timeout=10)
        print("Lejátszás elindult. Leállítás: Ctrl+C")

        while controller.status.player_state not in {"IDLE", "UNKNOWN"}:
            time.sleep(1)
            controller.update_status()
    except KeyboardInterrupt:
        print("\nLejátszás leállítása...")
        controller.stop()
    finally:
        server.shutdown()
        server.server_close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    file_path = args.file.expanduser().resolve()
    if not args.list and (not file_path.is_file() or file_path.stat().st_size == 0):
        print(f"Hiba: nem található vagy üres az MP3: {file_path}", file=sys.stderr)
        return 2

    print(f"Cast eszközök keresése ({args.timeout:g} másodperc)...")
    browser = None
    groups: list[Any] = []
    try:
        groups, browser = discover_groups(args.timeout)
        if args.list:
            if not groups:
                print("Nem található speaker group.")
                return 1
            for group in groups:
                print(f"- {group.name} ({group.cast_info.host})")
            return 0

        group = choose_group(groups, args.group)
        play(group, file_path, args.host_ip, args.port)
        return 0
    except (RuntimeError, OSError, pychromecast.error.PyChromecastError) as error:
        print(f"Hiba: {error}", file=sys.stderr)
        return 1
    finally:
        for group in groups:
            group.disconnect(timeout=2)
        if browser is not None:
            pychromecast.discovery.stop_discovery(browser)


if __name__ == "__main__":
    raise SystemExit(main())
