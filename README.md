# KeyPulse

**English** · [简体中文](README.zh-CN.md)

A 3D keyboard and gamepad heatmap for Windows. It counts how often you press
each key and each controller button, paints the counts onto a rendered board,
and files every run away in a gallery when you reset.

![The keyboard view](docs/preview-keyboard.png)

![The gamepad view](docs/preview-gamepad.png)

---

## Privacy — read this first

KeyPulse installs a low-level Windows keyboard hook, which is the same
mechanism a keylogger uses. So it is worth being exact about what it does with
it, and the code is short enough to check yourself.

**It stores one number per key.** `SPACE: 11329`. That is the whole record.

* It never stores the *order* keys were pressed in, so no typed text, password,
  or message can be reconstructed from its files. Compare
  [`hook.py`](hook.py): the callback maps a virtual-key code to a name and calls
  `on_press(key_id)`. The name is used as a dictionary key in
  [`storage.py`](storage.py) and the counter behind it is incremented. Nothing
  is appended to a list, and no timestamp is kept per press.
* It never records which window or application was focused.
* **It has no network code at all.** No telemetry, no update check, no
  analytics, no account. `grep -rE "urllib|requests|socket|http" *.py` comes
  back empty. Your counts do not leave your machine unless you copy them off it
  yourself.
* Everything it writes lands in plain, readable JSON next to the program, so
  you can open it and see exactly what is there.

Your antivirus may still flag a keyboard hook on principle, and Windows
SmartScreen will warn about the unsigned binary. That is expected; see
[Running it](#running-it).

## What it does

* **Two devices, counted at once.** The keyboard and the controller keep
  separate counts, and both keep counting whichever one is on screen.
* **Four keyboard layouts** — full 104-key, TKL, 75%, 60% — drawn in
  perspective, near keys larger and showing their sides.
* **Four controller models** — Xbox, DualSense, Switch Pro, and a plain wired
  XInput pad — each with its own button arrangement.
* **A heat colour per keycap** with the press count printed on it, so the keys
  you lean on are obvious at a glance.
* **Optional RGB lighting** modelled on per-switch backlighting: a rainbow wave
  under the keycaps, a white flash on each press. Off by default, and it stops
  drawing entirely when off or minimised, so it costs no CPU.
* **A gallery.** Every reset archives the run as a `.png` of the board plus a
  `.json` of the counts behind it, hung on a wall you can browse, open, and
  delete from.
* **English and Chinese**, switched from the header. The data files stay
  English either way. The full user guide
  ([docs/USER_GUIDE.zh-CN.txt](docs/USER_GUIDE.zh-CN.txt)) is Chinese only for
  now; this README is the English reference.
* **Tray and autostart.** Closing the window keeps it counting from the tray.

## Running it

### From a release

Download `KeyPulse_vX.Y.Z_Windows_x64.zip` from
[Releases](../../releases), unzip it, and double-click `KeyPulse.exe`. There is
no installer.

The binary is unsigned, so on first run Windows SmartScreen will show a blue
"Windows protected your PC" box. Choose **More info → Run anyway** if you trust
where you got it from. If you would rather not, build it yourself — see below.

### From source

Requires Python 3.11+ on Windows.

```powershell
pip install -r requirements.txt
python main.py
```

Useful flags:

| Flag | What it does |
| --- | --- |
| `--demo` | Fill both devices with plausible counts, for screenshots |
| `--no-hook` | Run the window without installing the keyboard hook |
| `--background` | Start hidden in the tray |
| `--screenshot PATH` | Render the window to a PNG and exit |
| `--device keyboard\|gamepad` | Which device a `--screenshot` run captures |

## Building the binary

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

`build.ps1` checks the environment, runs the whole test suite, builds a
one-file exe with PyInstaller, and writes `release/KeyPulse_vX.Y.Z_Windows_x64.zip`
— the exe plus the licence, the notices, and the user guide. Pass `-NoPause` in
CI, `-OutDir` to write the zip somewhere else, and `-InstallTo <folder>` to
drop the fresh exe into the folder you actually run KeyPulse from. The version
number lives in `build.ps1` and must match `version_info.txt`; the script
refuses to build if they disagree.

## Where your data lives

Beside the program — `KeyPulse.exe` and its files stay together, so a copy
carries its own counts and deleting the folder deletes all of it.

```
stats.json      the live counts for both devices
settings.json   layout, zoom, language, lighting, tray behaviour
snapshots/
  keyboard/     one .png + .json pair per archived keyboard run
  gamepad/      the same for the controller
```

If the program sits somewhere it cannot write — Program Files, a read-only
share — it falls back to `%LOCALAPPDATA%\KeyPulse`.

## Tests

99 tests, no display required beyond an offscreen Qt platform.

```powershell
$env:PYTHONPATH = $PWD
python tests\test_core.py
python tests\test_lighting.py
python tests\test_gallery.py
python tests\test_i18n.py
```

## Project layout

| File | What lives there |
| --- | --- |
| `main.py` | Startup, CLI flags, single-instance lock, wiring hooks to the window |
| `ui.py` | The main window, header, tray, reset flow, snapshot rendering |
| `render.py` | The 3D keyboard canvas and its lighting |
| `layouts.py` | The four keyboard layouts |
| `pad_canvas.py` | The controller canvas |
| `gamepads.py` | The four controller models |
| `pad_reference.py` | Controller outlines as numeric coordinates |
| `hook.py` | The low-level keyboard hook |
| `gamepad_hook.py` | XInput polling |
| `storage.py` | stats.json, settings.json, snapshots, autostart |
| `gallery.py` | The archive wall and the exhibit detail page |
| `i18n.py` | English and Chinese strings |

## Contributing

Bug reports and pull requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

Built with Python, PySide6/Qt (LGPLv3), and PyInstaller. See
[THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt), which also covers what the
LGPL asks of anyone redistributing the binary.

Xbox, PlayStation, DualSense, and Nintendo Switch are trademarks of their
respective owners. KeyPulse is not affiliated with or endorsed by any of them;
the names identify which controller layout is on screen, and the controllers
are drawn from numeric outlines rather than from any manufacturer's artwork.
