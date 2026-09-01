# Security policy

## Reporting a vulnerability

Please report security issues privately: use GitHub's
**Security → Report a vulnerability** on this repository rather than opening a
public issue. You should get a first reply within a week.

## Scope

KeyPulse is a local Windows desktop application. It has no server, no network
code, and no account system, so the interesting surface is small and specific:

* **The keyboard hook** (`hook.py`) — anything that lets it capture or persist
  more than a per-key count. That is the property the whole program rests on.
* **The data files** (`storage.py`) — path handling, the folders it adopts
  files from at startup, and the atomic writes.
* **Autostart** — the registry key it writes when "start with Windows" is on.
* **The build** (`build.ps1`, `KeyPulseOnefile.spec`) — anything that could get
  unexpected code into the released binary.

## What KeyPulse deliberately does

Two behaviours look alarming out of context and are documented rather than
fixed, so please do not report them as vulnerabilities:

* **It installs a low-level keyboard hook.** That is how it counts. It stores
  one integer per key and never the order they were pressed in — see the
  privacy section of the README.
* **The released binary is unsigned**, so SmartScreen warns about it. Code
  signing costs money the project does not have. Build it yourself from source
  if that matters to you.
