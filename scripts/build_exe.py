"""Freeze `stock.launch` into a windowed application with PyInstaller.

    .venv/Scripts/python.exe scripts/build_exe.py [--desktop] [--installer]

Writes `dist/Stock/` (one folder: `Stock.exe` and its `_internal/`). A folder app starts
at once, where a single-file exe must unpack itself on every launch. It has no console:
double-clicking opens the game in the default browser, and it quits by itself a few
minutes after the last page is closed (`stock/launch.py`). The icon is `scripts/stock.ico`
(`scripts/make_icon.py` draws it).

With `--desktop`, the app is copied to `%LOCALAPPDATA%/Programs/Stock` and a `Stock`
shortcut, with its icon, is put on the desktop. The shortcut's icon file is named for its
content, so a new icon shows at once instead of Windows' cached old one.

With `--installer`, it also writes `dist/Stock-Setup.exe`, an install wizard with the app
compressed inside it (`scripts/setup_wizard.py`), and `dist/Stock-Setup.zip` holding it.

The Mac version is built from `mac/` (`mac/build_mac.py`), which uses `build()` here.

`stock/server.py` locates the UI relative to its own `__file__`, which PyInstaller resolves
inside the bundle, so no path in the package changes when frozen. Build scratch goes to
`.pyinstaller/` (never `build/`).
"""

from __future__ import annotations

import ctypes
import filecmp
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".pyinstaller"
ICON = ROOT / "scripts" / "stock.ico"
README = """Stock: Adam Smith's four stages

Unzip, then run Stock-Setup.exe and follow the wizard. It installs for you alone,
with no administrator rights. The game opens in your web browser.

Windows may warn that the publisher is unknown (the setup is not signed):
choose More info, then Run anyway.
"""


def build(icon: Path = ICON, extra: Sequence[str] = ()) -> Path:
    """The one-folder app: `dist/Stock/` on Windows, `dist/Stock.app` on a Mac."""

    sep = os.pathsep
    PyInstaller.__main__.run(
        [
            str(ROOT / "stock" / "launch.py"),
            "--name",
            "Stock",
            "--onedir",
            "--windowed",
            "--noconfirm",
            "--clean",
            "--icon",
            str(icon),
            "--paths",
            str(ROOT),
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(SCRATCH / "work"),
            "--specpath",
            str(SCRATCH),
            "--add-data",
            f"{ROOT / 'stock' / 'web'}{sep}stock/web",
            "--collect-submodules",
            "stock",
            "--collect-submodules",
            "uvicorn",
            # dependencies the game does not use: leaving them out makes a smaller, faster app
            "--exclude-module",
            "numpy",
            "--exclude-module",
            "yaml",
            "--exclude-module",
            "PIL",
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "pytest",
            "--exclude-module",
            "mypy",
            *extra,
        ]
    )
    return ROOT / "dist" / ("Stock.app" if sys.platform == "darwin" else "Stock")


def desktop_folder() -> Path:
    """The real desktop, wherever Windows keeps it (OneDrive may have moved it)."""

    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _sync(src: Path, dst: Path) -> None:
    """Make `dst` a copy of `src`, touching only what changed: Stock may be running from
    `dst`, and Windows will not let a running program's files be replaced."""

    busy: list[Path] = []
    wanted = set()
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        t = dst / f.relative_to(src)
        wanted.add(t)
        if t.exists() and filecmp.cmp(f, t, shallow=False):
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(f, t)
        except PermissionError:
            busy.append(t)
    if busy:
        raise SystemExit(
            f"Stock is running: close it (and its browser tab) and install again. In use: {busy[0]}"
        )
    for t in dst.rglob("*"):  # what the new build no longer has
        if t.is_file() and t not in wanted and not t.name.startswith("stock-"):
            t.unlink(missing_ok=True)


def install(app: Path) -> Path:
    """Copy the app beside the user's other programs and put a shortcut on the desktop."""

    home = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Stock"
    _sync(app, home)
    return shortcut(home)


def shortcut(home: Path) -> Path:
    """The desktop shortcut to the installed app, with the current icon."""

    # Windows caches icons by file path, so a rebuilt Stock.exe would keep showing the old
    # picture: the shortcut points at an .ico named for its content, which is always new
    digest = hashlib.sha256(ICON.read_bytes()).hexdigest()[:10]
    icon = home / f"stock-{digest}.ico"
    for old in home.glob("stock-*.ico"):
        if old != icon:
            old.unlink(missing_ok=True)
    shutil.copyfile(ICON, icon)
    link = desktop_folder() / "Stock.lnk"
    link.unlink(missing_ok=True)
    exe = home / "Stock.exe"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK);"
        "$s.TargetPath = $env:EXE; $s.WorkingDirectory = $env:HOME_DIR;"
        "$s.IconLocation = $env:ICON + ',0'; $s.Description = 'Stock: Smith''s four stages';"
        "$s.Save()"
    )
    env = {**os.environ, "LINK": str(link), "EXE": str(exe), "HOME_DIR": str(home), "ICON": str(icon)}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True)
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED: redraw icons
    return link


def installer(app: Path) -> tuple[Path, Path]:
    """`dist/Stock-Setup.exe`: the install wizard (`scripts/setup_wizard.py`) with the app
    zipped inside it; and `dist/Stock-Setup.zip`, the wizard in a zip, for sending where a
    bare .exe would be refused."""

    payload = SCRATCH / "payload"
    if payload.exists():
        shutil.rmtree(payload)
    payload.mkdir(parents=True)
    with zipfile.ZipFile(payload / "Stock.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app).as_posix())
    shutil.copyfile(ICON, payload / "stock.ico")
    shutil.copyfile(ROOT / "stock" / "web" / "icon.png", payload / "icon.png")
    PyInstaller.__main__.run(
        [
            str(ROOT / "scripts" / "setup_wizard.py"),
            "--name",
            "Stock-Setup",
            "--onefile",
            "--windowed",
            "--noconfirm",
            "--clean",
            "--icon",
            str(ICON),
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(SCRATCH / "work-setup"),
            "--specpath",
            str(SCRATCH),
            "--add-data",
            f"{payload}{os.pathsep}payload",
            "--exclude-module",
            "numpy",
            "--exclude-module",
            "PIL",
        ]
    )
    setup = ROOT / "dist" / "Stock-Setup.exe"
    archive = ROOT / "dist" / "Stock-Setup.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(setup, setup.name)
        z.writestr("READ ME.txt", "\r\n".join(README.splitlines()) + "\r\n")
    return setup, archive


def main() -> None:
    if sys.platform == "darwin":
        sys.exit("On a Mac, build with mac/build_mac.py")
    app = build()
    if "--desktop" in sys.argv[1:]:
        print(f"Shortcut: {install(app)}")
    if "--installer" in sys.argv[1:]:
        for f in installer(app):
            print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
