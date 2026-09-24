"""Freeze `stock.launch` into a windowed application with PyInstaller.

    .venv/Scripts/python.exe scripts/build_exe.py [--desktop]

Writes `dist/Stock/` (one folder: `Stock.exe` and its `_internal/`). A folder app starts
at once, where a single-file exe must unpack itself on every launch. It has no console:
double-clicking opens the game in the default browser, and it quits by itself a few
minutes after the last page is closed (`stock/launch.py`). The icon is `scripts/stock.ico`
(`scripts/make_icon.py` draws it).

With `--desktop`, the app is copied to `%LOCALAPPDATA%/Programs/Stock` and a `Stock`
shortcut, with its icon, is put on the desktop.

`stock/server.py` locates the UI relative to its own `__file__`, which PyInstaller resolves
inside the bundle, so no path in the package changes when frozen. Build scratch goes to
`.pyinstaller/` (never `build/`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".pyinstaller"
ICON = ROOT / "scripts" / "stock.ico"


def build() -> Path:
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
            str(ICON),
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
        ]
    )
    return ROOT / "dist" / "Stock"


def desktop_folder() -> Path:
    """The real desktop, wherever Windows keeps it (OneDrive may have moved it)."""

    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def install(app: Path) -> Path:
    """Copy the app beside the user's other programs and put a shortcut on the desktop."""

    home = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Stock"
    if home.exists():
        shutil.rmtree(home)
    shutil.copytree(app, home)
    link = desktop_folder() / "Stock.lnk"
    exe = home / "Stock.exe"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK);"
        "$s.TargetPath = $env:EXE; $s.WorkingDirectory = $env:HOME_DIR;"
        "$s.IconLocation = $env:EXE + ',0'; $s.Description = 'Stock: Smith''s four stages';"
        "$s.Save()"
    )
    env = {**os.environ, "LINK": str(link), "EXE": str(exe), "HOME_DIR": str(home)}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True)
    return link


def main() -> None:
    app = build()
    if "--desktop" in sys.argv[1:]:
        print(f"Shortcut: {install(app)}")


if __name__ == "__main__":
    main()
