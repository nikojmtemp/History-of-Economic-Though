"""Build Stock for the web: a static site that runs the whole game in the browser.

    .venv/Scripts/python.exe scripts/build_web.py [--out site]

Writes `site/`, ready for GitHub Pages or any static host:

- `index.html`, the desktop app's page with relative paths, a loading screen, and two more
  scripts: Pyodide (Python in WebAssembly, from the jsDelivr CDN) and `boot.js`;
- `app.js`, `app.css`, `tokens.css`, `icon.png`, `boot.js`: the UI, unchanged;
- `stock.zip`: the engine (`stock/game`), the service, saves, and `stock/browser.py`, which
  keeps saves in the browser's own storage. The desktop server is left out.

Every file is stamped with a hash of its content, so a new version is never mixed with a
cached old one. To try it locally: `python -m http.server -d site 8200`.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "stock" / "web"
PYODIDE_JS = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.js"
ASSETS = ("app.js", "app.css", "tokens.css", "icon.png", "boot.js")
ENGINE = ("__init__.py", "saves.py", "service.py", "browser.py")

LOADING = """<div id="loading">
  <div class="card">
    <img src="icon.png" alt="" width="128" height="128">
    <h1>Stock</h1>
    <p class="sub">Adam Smith's four stages</p>
    <p class="what">Loading…</p>
  </div>
</div>
<style>
  #loading { position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center;
    background: var(--paper); color: var(--ink); font-family: var(--serif, Georgia, serif); }
  #loading .card { text-align: center; max-width: 420px; padding: 24px; }
  #loading h1 { margin: 8px 0 0; font-size: 34px; }
  #loading .sub { margin: 2px 0 18px; font-style: italic; color: var(--ink-2); }
  #loading .what { font-family: var(--sans, sans-serif); font-size: 14px; color: var(--ink-2); }
  #loading.failed .what { color: var(--down); }
</style>
"""


def stamp(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def engine_zip() -> bytes:
    """The package as Pyodide unpacks it: stock/ with the engine, the service and saves."""

    out = Path(ROOT / ".pyinstaller" / "stock-web.zip")
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in ENGINE:
            z.write(ROOT / "stock" / name, f"stock/{name}")
        for f in sorted((ROOT / "stock" / "game").glob("*.py")):
            z.write(f, f"stock/game/{f.name}")
    return out.read_bytes()


def build(site: Path) -> Path:
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    stamps = {}
    for name in ASSETS:
        data = (WEB / name).read_bytes()
        (site / name).write_bytes(data)
        stamps[name] = stamp(data)
    zipped = engine_zip()
    (site / "stock.zip").write_bytes(zipped)

    html = (WEB / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "app.css", "tokens.css", "icon.png"):
        html = html.replace(f"/static/{name}", f"{name}?v={stamps[name]}")
    html = html.replace("<body>", "<body>\n" + LOADING, 1)
    scripts = (
        f'<script src="{PYODIDE_JS}"></script>\n'
        f'<script src="boot.js?v={stamps["boot.js"]}" data-stamp="{stamp(zipped)}"></script>\n'
    )
    marker = f'<script src="app.js?v={stamps["app.js"]}"></script>'
    assert marker in html, "index.html must load app.js from /static/app.js"
    html = html.replace(marker, scripts + marker, 1)
    (site / "index.html").write_text(html, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return site


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "site")
    site = build(ap.parse_args().out)
    size = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    print(f"{site}: {len(list(site.iterdir()))} files, {size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
