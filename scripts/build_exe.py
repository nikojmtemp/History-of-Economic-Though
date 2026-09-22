"""Freeze `stock.launch` into a single executable with PyInstaller.

    .venv/Scripts/python.exe scripts/build_exe.py

Writes `dist/Stock.exe` (on Windows; `dist/Stock` elsewhere). The bundle carries the
engine and the static UI (worlds are generated, `stock/game/worldgen`); `stock/
server.py` locates the UI relative to its own `__file__`, which PyInstaller resolves
inside the unpacked bundle, so no path in the package changes when frozen. Build
scratch goes to `.pyinstaller/` (never `build/`).
"""

from __future__ import annotations

import os
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / ".pyinstaller"


def main() -> None:
    sep = os.pathsep
    PyInstaller.__main__.run(
        [
            str(ROOT / "stock" / "launch.py"),
            "--name",
            "Stock",
            "--onefile",
            "--noconfirm",
            "--clean",
            "--console",
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
            "--collect-submodules",
            "websockets",
        ]
    )


if __name__ == "__main__":
    main()
