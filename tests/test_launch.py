"""`stock.launch`: the play entry point (and what `dist/Stock.exe` runs)."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from stock.launch import HOST, free_port, open_when_ready, parse_args


def test_free_port_falls_back_when_the_preferred_one_is_taken() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind((HOST, 0))
        taken.listen(1)
        busy = int(taken.getsockname()[1])
        port = free_port(preferred=busy)
        assert port != busy and port > 0


def test_open_when_ready_opens_the_browser_once_the_server_answers() -> None:
    class Quiet(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer((HOST, 0), Quiet)
    port = server.server_address[1]
    opened: list[str] = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    try:
        # Start waiting before the server serves: the launcher must poll, not race.
        url = f"http://{HOST}:{port}"
        waiter = threading.Thread(target=lambda: open_when_ready(url, opener=opened.append))
        waiter.start()
        thread.start()
        waiter.join(timeout=10)
        assert opened == [url]
    finally:
        server.shutdown()
        server.server_close()


def test_open_when_ready_gives_up_and_tells_the_player(capsys: object) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        dead = int(sock.getsockname()[1])  # bound, never listening: connections are refused
    opened: list[str] = []
    assert not open_when_ready(f"http://{HOST}:{dead}", opener=opened.append, timeout=0.5)
    assert opened == []


def test_arguments() -> None:
    args = parse_args(["--port", "9000", "--no-browser"])
    assert args.port == 9000 and args.no_browser and args.scenario is None
    assert parse_args([]).port is None
