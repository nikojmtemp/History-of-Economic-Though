# Stock for the Mac

Everything the Mac version needs, in one folder. Copy the whole project to a Mac (the game's source lives in `../stock`) and use one of the two double-click scripts.

| File | What it does |
|---|---|
| `play.command` | Plays Stock straight from the source, with no app to build. The first run sets up Python in `.venv-mac`; after that the game opens in your browser at once. |
| `build.command` | Builds `dist/Stock.app` and `dist/Stock.dmg`, a disk image to drag Stock into Applications, then opens `dist`. |
| `build_mac.py` | The build that `build.command` runs. It uses the shared PyInstaller step in `../scripts/build_exe.py`, adds the Mac icon, hides the Dock icon, signs the app ad hoc and makes the disk image. |
| `stock.icns` | The Mac icon: Adam Smith in profile, drawn by `../scripts/make_icon.py`. |

Both scripts need Python 3.12 or newer. Install it from python.org if `python3 --version` shows an older one. If macOS won't open a `.command` file, right-click it and choose **Open**, or run it in Terminal:

```bash
bash mac/build.command
```

## The app

Double-clicking **Stock** opens the game in the default browser. The app has no window or Dock icon of its own, and it quits by itself a few minutes after the game's tab is closed. If you double-click it again while it is still running, nothing new happens, because macOS just wakes the running copy; reopen the game's tab instead. Logs go to `~/Library/Logs/Stock`.

The app is signed ad hoc, not with an Apple Developer ID, so the first launch needs a right-click on Stock, **Open**, then **Open** again. On recent macOS, if there's no Open button, go to System Settings, Privacy & Security, **Open Anyway**. The build is for Apple silicon (M1 and later) when made on one; an Intel Mac builds its own.

## Without a Mac

PyInstaller can't build a Mac app on Windows. Push the project to GitHub and run the **Build** workflow (`../.github/workflows/build.yml`) from the Actions tab. It builds `Stock.dmg` on GitHub's macOS machines, alongside the Windows installer.
