"""Build Stock for the Mac: `dist/Stock.app` and `dist/Stock.dmg`.

    python3 mac/build_mac.py          (or double-click mac/build.command)

Must run on a Mac: PyInstaller cannot cross-build. The app is the same one-folder build
as on Windows (`scripts/build_exe.py`'s `build()`), with the Mac icon (`mac/stock.icns`).
It has no Dock icon, because the browser is its window, and it logs to
`~/Library/Logs/Stock`. The disk image holds the app beside a link to Applications, the
usual drag to install, and a short READ ME.

The app is signed ad hoc, not with an Apple Developer ID, so the first launch needs
right-click, Open (or System Settings, Privacy & Security, Open Anyway).
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

BUNDLE_ID = "org.stockgame.stock"
VERSION = "1.0"
README = """Stock: Adam Smith's four stages

Drag Stock onto Applications, then open it from there. The game opens in your web
browser; there is no window of its own, and it quits by itself a few minutes after
you close the game's tab.

The app is not signed by an identified developer, so the first time macOS will refuse:
right-click (or Control-click) Stock, choose Open, then Open again. On recent macOS,
if there is no Open button: System Settings, Privacy & Security, Open Anyway.
"""


def mac_app(app: Path) -> None:
    """No Dock icon (the app is a server; the browser is its window), a version, then a fresh
    ad hoc signature, since editing Info.plist breaks the one PyInstaller made."""

    info = app / "Contents" / "Info.plist"
    plist = plistlib.loads(info.read_bytes())
    plist.update(
        LSUIElement=True,
        CFBundleDisplayName="Stock",
        CFBundleShortVersionString=VERSION,
        CFBundleVersion=VERSION,
        NSHumanReadableCopyright="Stock: Adam Smith's four stages",
    )
    info.write_bytes(plistlib.dumps(plist))
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)


def dmg(app: Path) -> Path:
    """`dist/Stock.dmg`: the app beside a link to Applications, and the READ ME."""

    stage = ROOT / ".pyinstaller" / "dmg"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)  # keeps links and signature
    (stage / "Applications").symlink_to("/Applications")
    (stage / "READ ME.txt").write_text(README, encoding="utf-8")
    out = ROOT / "dist" / "Stock.dmg"
    out.unlink(missing_ok=True)
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "Stock",
            "-srcfolder",
            str(stage),
            "-ov",
            "-format",
            "UDZO",
            str(out),
        ],
        check=True,
    )
    return out


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("The Mac version must be built on a Mac (PyInstaller cannot cross-build).")
    from build_exe import build  # scripts/build_exe.py: the shared PyInstaller step

    app = build(icon=HERE / "stock.icns", extra=["--osx-bundle-identifier", BUNDLE_ID])
    mac_app(app)
    out = dmg(app)
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
