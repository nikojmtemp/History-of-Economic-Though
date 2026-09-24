"""Play: start the server on a free local port and open the game in the system's
default browser.

    python -m stock.launch [--port N] [--no-browser] [--scenario SPEC] [--quit-when-idle S]

`scripts/build_exe.py` freezes this entry point into a windowed `Stock.exe` (PyInstaller)
that carries the UI and the engine; double-clicking it does the same thing, with no
console. The frozen app quits by itself a few minutes after the last page is closed
(the page sends a heartbeat), and a second launch while it runs just opens the game
again in the browser.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable, Sequence

PREFERRED_PORT = 8123
HOST = "127.0.0.1"


def free_port(preferred: int = PREFERRED_PORT) -> int:
    """`preferred` if nothing is listening on it, else a port the OS hands out."""

    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise RuntimeError("no free local port")


FROZEN = bool(getattr(sys, "frozen", False))
IDLE_QUIT = 180.0  # seconds without a page before the frozen app quits


def running_stock(port: int = PREFERRED_PORT) -> bool:
    """Whether Stock already answers on `port` (a second launch opens that game instead)."""

    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/alive", timeout=0.5) as r:
            return bool(json.load(r).get("app") == "stock")
    except (OSError, ValueError):
        return False


def log_to_file() -> None:
    """A windowed app has no console: keep what it would print in a log instead."""

    folder = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Stock")
    os.makedirs(folder, exist_ok=True)
    log = open(os.path.join(folder, "stock.log"), "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = log


def quit_when_idle(server: object, app: object, idle: float) -> None:
    """Stop the server once no page has called for `idle` seconds."""

    while not getattr(server, "should_exit", False):
        time.sleep(min(5.0, idle / 4))
        if time.monotonic() - app.state.last_seen > idle:  # type: ignore[attr-defined]
            server.should_exit = True  # type: ignore[attr-defined]


def wait_until_serving(url: str, timeout: float = 30.0, interval: float = 0.05) -> bool:
    """True once `url` answers any HTTP status; False after `timeout` seconds."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0):
                return True
        except urllib.error.HTTPError:
            return True  # the server is up; it just didn't like the request
        except (urllib.error.URLError, OSError):
            time.sleep(interval)
    return False


def open_when_ready(
    url: str, *, opener: Callable[[str], object] = webbrowser.open, timeout: float = 30.0
) -> bool:
    """Opens `url` in the default browser as soon as the server answers."""

    if not wait_until_serving(f"{url}/scenario", timeout=timeout):
        print(f"The server did not answer within {timeout:.0f}s; open {url} yourself.", file=sys.stderr)
        return False
    opener(url)
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="stock", description="Play Stock in your browser.")
    port_help = f"listen on this port (default: {PREFERRED_PORT}, or a free one if that is taken)"
    parser.add_argument("--port", type=int, default=None, help=port_help)
    parser.add_argument("--no-browser", action="store_true", help="start the server without a browser")
    parser.add_argument(
        "--quit-when-idle",
        type=float,
        default=IDLE_QUIT if FROZEN else 0.0,
        help="quit after this many seconds with no page open (0: never; the default when not frozen)",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help=(
            "random[:seed[:locations[:nations]]] for a generated world (default: a fresh seed), "
            "or a scenario YAML file"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if sys.stdout is None:  # a windowed build
        log_to_file()
    args = parse_args(argv)
    if args.port is None and not args.no_browser and running_stock():
        webbrowser.open(f"http://{HOST}:{PREFERRED_PORT}")  # already running: show it again
        return 0
    import uvicorn

    from stock.server import create_app

    port = args.port if args.port is not None else free_port()
    url = f"http://{HOST}:{port}"
    app = create_app(args.scenario)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))

    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    if args.quit_when_idle > 0:
        threading.Thread(target=quit_when_idle, args=(server, app, args.quit_when_idle), daemon=True).start()
    print(f"Stock is running at {url}")
    if args.quit_when_idle > 0:
        print(f"It stops by itself {args.quit_when_idle:.0f}s after the last page is closed.")
    else:
        print("Close this window (or press Ctrl+C) to stop the game.")
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
