"""The Stock install wizard: one compressed `Stock-Setup.exe` that installs the game.

Frozen by `scripts/build_exe.py --installer`, with the built app zipped inside it
(`payload/Stock.zip`) and the logo (`payload/icon.png`). Pages: Welcome, Folder, Options,
Installing, Finished. It installs for the current user only (no administrator rights),
makes the chosen shortcuts, registers an uninstaller in Windows' Apps & features, and can
launch the game at the end. Run as `Uninstall Stock.exe` (a copy of itself, left in the
install folder) or with `--uninstall`, it removes all of that again.

    Stock-Setup.exe [--silent] [--dir PATH] [--no-shortcuts] [--no-register] [--no-launch]

`--silent` installs with no window, for scripted installs and tests.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import winreg
import zipfile
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP = "Stock"
VERSION = "1.0"
PUBLISHER = "Stock"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Stock"
UNINSTALLER = "Uninstall Stock.exe"

PAPER, PAPER_2, INK, INK_2, ACCENT = "#F4EFE4", "#EAE3D3", "#1E1B16", "#6B6252", "#3B5B8C"


# --- where things go -----------------------------------------------------------------------


def bundled(name: str) -> Path:
    """A file carried inside the frozen setup (from source: the build's `.pyinstaller/payload`)."""

    frozen = getattr(sys, "_MEIPASS", None)
    base = Path(frozen) if frozen else Path(__file__).resolve().parent.parent / ".pyinstaller"
    return base / "payload" / name


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / APP


def known_folder(csidl: int) -> Path:
    """Desktop (0x10) or the Start Menu's Programs (0x02), wherever Windows keeps them."""

    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def desktop_link() -> Path:
    return known_folder(0x10) / f"{APP}.lnk"


def menu_link() -> Path:
    return known_folder(0x02) / f"{APP}.lnk"


# --- the work -------------------------------------------------------------------------------


class Busy(Exception):
    """Stock is running from the folder being replaced."""


def extract(target: Path, progress: Callable[[float], None]) -> None:
    """Unpack the app into `target`, replacing only what differs."""

    with zipfile.ZipFile(bundled("Stock.zip")) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        total = sum(m.file_size for m in members) or 1
        done = 0
        for m in members:
            dest = target / m.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = z.read(m)
            if not (dest.exists() and dest.stat().st_size == len(data) and dest.read_bytes() == data):
                try:
                    dest.write_bytes(data)
                except PermissionError as exc:
                    raise Busy(str(dest)) from exc
            done += m.file_size
            progress(done / total)


def make_shortcut(link: Path, target: Path) -> None:
    """A shortcut with the logo. The icon file is named for its content, so Windows' icon
    cache never shows an older picture."""

    icon_src = bundled("stock.ico")
    icon = target / f"stock-{hashlib.sha256(icon_src.read_bytes()).hexdigest()[:10]}.ico"
    if not icon.exists():
        for old in target.glob("stock-*.ico"):
            old.unlink(missing_ok=True)
        shutil.copyfile(icon_src, icon)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK);"
        "$s.TargetPath = $env:EXE; $s.WorkingDirectory = $env:DIR; $s.IconLocation = $env:ICON + ',0';"
        "$s.Description = 'Stock: Adam Smith''s four stages'; $s.Save()"
    )
    env = {
        **os.environ,
        "LINK": str(link),
        "EXE": str(target / f"{APP}.exe"),
        "DIR": str(target),
        "ICON": str(icon),
    }
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        env=env,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def register(target: Path) -> None:
    """An entry in Apps & features, so Stock can be removed like any other program."""

    if getattr(sys, "frozen", False):
        shutil.copyfile(sys.executable, target / UNINSTALLER)
    size_kb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) // 1024
    icon = next(target.glob("stock-*.ico"), target / f"{APP}.exe")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, value in {
            "DisplayName": APP,
            "DisplayVersion": VERSION,
            "Publisher": PUBLISHER,
            "DisplayIcon": str(icon),
            "InstallLocation": str(target),
            "UninstallString": f'"{target / UNINSTALLER}" --uninstall',
        }.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def installed_dir() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return Path(winreg.QueryValueEx(k, "InstallLocation")[0])
    except OSError:
        return None


def link_target(link: Path) -> Path | None:
    if not link.exists():
        return None
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK).TargetPath",
        ],
        env={**os.environ, "LINK": str(link)},
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return Path(out.stdout.strip()) if out.stdout.strip() else None


def ours(path: Path | None, target: Path) -> bool:
    """Whether `path` lies in the install folder `target` (and so is ours to remove)."""

    return path is not None and target.resolve() in (path.resolve(), *path.resolve().parents)


def uninstall(target: Path) -> None:
    """Remove the app in `target`, and only the shortcuts and registration that belong to it."""

    for link in (desktop_link(), menu_link()):
        if ours(link_target(link), target):
            link.unlink(missing_ok=True)
    if ours(installed_dir(), target):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        except OSError:
            pass
    for f in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if f.is_file() and f.name != UNINSTALLER:
            try:
                f.unlink()
            except PermissionError as exc:
                raise Busy(str(f)) from exc
        elif f.is_dir():
            try:
                f.rmdir()
            except OSError:
                pass
    # this uninstaller is running from the folder: let a moment pass, then take both away
    subprocess.Popen(
        f'cmd /c ping -n 3 127.0.0.1 >nul & del /f /q "{target / UNINSTALLER}" & rmdir /q "{target}"',
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def refresh_icons() -> None:
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def launch(target: Path) -> None:
    subprocess.Popen([str(target / f"{APP}.exe")], cwd=str(target))


# --- the wizard ---------------------------------------------------------------------------


class Wizard(tk.Tk):
    def __init__(self, uninstalling: bool) -> None:
        super().__init__()
        self.uninstalling = uninstalling
        self.title(f"Remove {APP}" if uninstalling else f"{APP} Setup")
        self.geometry("620x420")
        self.resizable(False, False)
        self.configure(bg=PAPER)
        try:
            self.iconbitmap(default=str(bundled("stock.ico")))
        except tk.TclError:
            pass
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PAPER, foreground=INK, font=("Segoe UI", 10))
        style.configure("TButton", padding=(14, 5), background=PAPER_2)
        style.map("TButton", background=[("active", "#DDD3BD")])
        style.configure("Primary.TButton", background=ACCENT, foreground=PAPER)
        style.map("Primary.TButton", background=[("active", "#2E4A74")])
        style.configure("TCheckbutton", background=PAPER)
        style.configure("TEntry", fieldbackground="white")
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PAPER_2)

        self.target = tk.StringVar(value=str(installed_dir() or default_dir()))
        self.want_desktop = tk.BooleanVar(value=True)
        self.want_menu = tk.BooleanVar(value=True)
        self.want_launch = tk.BooleanVar(value=True)

        # the banner: Smith's cameo on the left, as in the game's own ledger colours
        side = tk.Frame(self, bg=INK, width=190)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        try:
            self.logo = tk.PhotoImage(file=str(bundled("icon.png"))).subsample(2, 2)
            tk.Label(side, image=self.logo, bg=INK).pack(pady=(40, 12))
        except tk.TclError:
            pass
        tk.Label(side, text=APP, bg=INK, fg=PAPER, font=("Georgia", 22, "bold")).pack()
        tk.Label(
            side, text="Adam Smith's\nfour stages", bg=INK, fg="#B8AE98", font=("Georgia", 11, "italic")
        ).pack(pady=(4, 0))

        self.body = tk.Frame(self, bg=PAPER)
        self.body.pack(side="top", fill="both", expand=True, padx=26, pady=(24, 0))
        bar = tk.Frame(self, bg=PAPER)
        bar.pack(side="bottom", fill="x", padx=20, pady=16)
        self.cancel = ttk.Button(bar, text="Cancel", command=self.destroy)
        self.cancel.pack(side="right")
        self.next = ttk.Button(bar, text="Next >", style="Primary.TButton")
        self.next.pack(side="right", padx=(0, 8))
        self.back = ttk.Button(bar, text="< Back")
        self.back.pack(side="right", padx=(0, 8))
        tk.Frame(self, bg="#D8CFBC", height=1).pack(side="bottom", fill="x")

        (self.remove_page if uninstalling else self.welcome)()

    # page helpers
    def page(self, title: str, text: str = "") -> tk.Frame:
        for w in self.body.winfo_children():
            w.destroy()
        tk.Label(self.body, text=title, bg=PAPER, fg=INK, font=("Georgia", 17, "bold"), anchor="w").pack(
            fill="x"
        )
        if text:
            tk.Label(
                self.body, text=text, bg=PAPER, fg=INK_2, justify="left", wraplength=380, anchor="w"
            ).pack(fill="x", pady=(10, 0))
        f = tk.Frame(self.body, bg=PAPER)
        f.pack(fill="both", expand=True, pady=(16, 0))
        return f

    def buttons(
        self, back: Callable[[], None] | None, next_text: str, nxt: Callable[[], None] | None
    ) -> None:
        self.back.configure(command=back or (lambda: None), state="normal" if back else "disabled")
        self.next.configure(
            text=next_text, command=nxt or (lambda: None), state="normal" if nxt else "disabled"
        )

    # install pages
    def welcome(self) -> None:
        self.page(
            f"Welcome to {APP}",
            "A turn-based game of Adam Smith's four stages of society: hunting, pasturage, "
            "agriculture and commerce. Lead a people from a hunting band to a commercial "
            "nation, through trade, war and the slow growth of stock.\n\n"
            "This wizard installs Stock for you alone; no administrator rights are needed. "
            "The game opens in your web browser.",
        )
        self.buttons(None, "Next >", self.folder)

    def folder(self) -> None:
        f = self.page("Where should Stock go?", "Stock will be installed in this folder.")
        row = tk.Frame(f, bg=PAPER)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.target).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self.browse).pack(side="left", padx=(8, 0))
        size = sum(m.file_size for m in zipfile.ZipFile(bundled("Stock.zip")).infolist()) / 1e6
        tk.Label(f, text=f"Space needed: about {size:.0f} MB", bg=PAPER, fg=INK_2).pack(
            anchor="w", pady=(10, 0)
        )
        self.buttons(self.welcome, "Next >", self.options)

    def browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.target.get(), title="Install Stock in")
        if chosen:
            path = Path(chosen)
            self.target.set(str(path if path.name.lower() == APP.lower() else path / APP))

    def options(self) -> None:
        f = self.page("A few choices")
        ttk.Checkbutton(f, text="Put a Stock icon on the desktop", variable=self.want_desktop).pack(
            anchor="w"
        )
        ttk.Checkbutton(f, text="Add Stock to the Start menu", variable=self.want_menu).pack(
            anchor="w", pady=6
        )
        ttk.Checkbutton(f, text="Play Stock when setup finishes", variable=self.want_launch).pack(anchor="w")
        self.buttons(self.folder, "Install", self.install_page)

    def install_page(self) -> None:
        f = self.page("Installing…", "Unpacking the game.")
        self.bar = ttk.Progressbar(f, length=380, mode="determinate", maximum=1.0)
        self.bar.pack(anchor="w")
        self.status = tk.Label(f, text="", bg=PAPER, fg=INK_2)
        self.status.pack(anchor="w", pady=(8, 0))
        self.buttons(None, "Next >", None)
        self.cancel.configure(state="disabled")
        threading.Thread(target=self.work, daemon=True).start()

    def work(self) -> None:
        target = Path(self.target.get())
        try:
            target.mkdir(parents=True, exist_ok=True)
            extract(target, lambda x: self.after(0, self.bar.configure, {"value": x}))
            self.after(0, self.status.configure, {"text": "Making shortcuts…"})
            if self.want_desktop.get():
                make_shortcut(desktop_link(), target)
            if self.want_menu.get():
                make_shortcut(menu_link(), target)
            register(target)
            refresh_icons()
        except Busy:
            self.after(0, self.busy)
            return
        except OSError as exc:
            why = str(exc)
            self.after(0, lambda: self.failed(why))
            return
        self.after(0, self.finished)

    def busy(self) -> None:
        self.cancel.configure(state="normal")
        messagebox.showwarning(
            APP, "Stock is running. Close its browser tab, wait a moment for it to stop, then try again."
        )
        self.options()

    def failed(self, why: str) -> None:
        self.cancel.configure(state="normal")
        messagebox.showerror(APP, f"Setup could not finish:\n{why}")
        self.options()

    def finished(self) -> None:
        self.page(
            f"{APP} is installed",
            "Double-click the Stock icon to play: the game opens in your browser, and closes "
            "itself a few minutes after you close its tab.\n\n"
            "To remove it, use Apps & features in Windows Settings.",
        )
        self.cancel.configure(state="disabled")
        self.buttons(None, "Finish", self.done)

    def done(self) -> None:
        if self.want_launch.get():
            launch(Path(self.target.get()))
        self.destroy()

    # the uninstaller's pages
    def remove_page(self) -> None:
        where = installed_dir() or Path(sys.executable).parent
        self.target.set(str(where))
        self.page(f"Remove {APP}?", f"Stock will be removed from\n{where}\nalong with its shortcuts.")
        self.buttons(None, "Remove", self.removing)

    def removing(self) -> None:
        try:
            uninstall(Path(self.target.get()))
        except Busy:
            messagebox.showwarning(
                APP, "Stock is running. Close its browser tab, wait a moment, then try again."
            )
            return
        self.page(f"{APP} has been removed", "Thank you for playing.")
        self.cancel.configure(state="disabled")
        self.buttons(None, "Finish", self.destroy)


# --- entry ----------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(prog="Stock-Setup")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--no-launch", action="store_true")
    args = ap.parse_args()
    uninstalling = args.uninstall or Path(sys.executable).name.lower().startswith("uninstall")
    if args.silent:
        target = args.dir or installed_dir() or default_dir()
        if uninstalling:
            uninstall(target)
            return 0
        target.mkdir(parents=True, exist_ok=True)
        extract(target, lambda _x: None)
        if not args.no_shortcuts:
            make_shortcut(desktop_link(), target)
            make_shortcut(menu_link(), target)
        if not args.no_register:
            register(target)
        refresh_icons()
        if not args.no_launch:
            launch(target)
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
    except (AttributeError, OSError):
        pass
    Wizard(uninstalling).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
