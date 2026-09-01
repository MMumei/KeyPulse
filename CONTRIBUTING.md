# Contributing to KeyPulse

Thanks for taking a look. Issues and pull requests are both welcome.

## Reporting a bug

Open an issue and include:

* what you did, what you expected, and what happened instead;
* the KeyPulse version (Help is in the window header, or check
  `version_info.txt`);
* your Windows version;
* if it concerns your counts or the gallery, the relevant part of `stats.json`
  or of the snapshot's `.json`. **Read it before you paste it** — it holds
  nothing but per-key counts, but it is your data and it is your call.

## Setting up

Windows and Python 3.11+.

```powershell
pip install -r requirements.txt
$env:PYTHONPATH = $PWD
python main.py --no-hook   # the window, without touching your real counts
```

`--no-hook` is worth getting into the habit of: it starts the window without
installing the keyboard hook, so a development run cannot pollute your own
statistics.

**Watch where the data goes.** KeyPulse writes `stats.json`, `settings.json`
and `snapshots/` *beside the program*, which when you run from source means
this very folder. They are in `.gitignore`; never commit them.

## Running the tests

All four suites, and all of them must pass before a build:

```powershell
$env:PYTHONPATH = $PWD
python tests\test_core.py
python tests\test_lighting.py
python tests\test_gallery.py
python tests\test_i18n.py
```

`build.ps1` runs them itself and refuses to build if any fail.

## House style

The code has a voice; please match it rather than reformat around it.

* **Comments explain *why*, not *what*.** The existing comments read like
  someone telling you what went wrong last time and what the code does about
  it. That is deliberate. A comment restating the line below it is noise.
* Type hints on function signatures; `from __future__ import annotations` at
  the top of every module.
* Standard library, then PySide6, then local imports.
* Keep lines within about 88 columns.
* No new dependencies without discussing it in an issue first. The whole app
  is PySide6 and the standard library, and that is a feature.

## Two things that need care

**The keyboard hook.** KeyPulse's promise is that it stores per-key counts and
nothing else. A change that records the order of presses, per-press timestamps,
the foreground window, or anything else that could reconstruct what someone
typed will not be merged. If you have a feature that seems to need it, open an
issue first and let us find another way.

**The data files.** `stats.json` holds counts people have accumulated for
months. Any change to its shape must keep reading the old shape — see how
`version` and the `devices` section are handled in `storage.py`, where the
keyboard deliberately still lives at the top level so that an older build can
read a file this one wrote.

## Adding a translation

`i18n.py` holds the strings. Two languages are wired in today, English and
Chinese; the structure takes more. Keep translations about as short as the
English, since the layout has no room to grow, and leave the data files
English — only what is on screen gets translated.

## Pull requests

Small and focused beats large and sweeping. Say what problem the change solves
in the description, and make sure the tests pass. If you changed behaviour that
the user guide describes, update `docs/USER_GUIDE.zh-CN.txt` too.
