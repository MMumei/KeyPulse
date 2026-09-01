from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


APP_NAME = "KeyPulse"
SNAPSHOT_DIR_NAME = "snapshots"


def _program_dir() -> Path:
    """The folder the program itself sits in, frozen into an exe or not."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _writable(folder: Path) -> bool:
    """Whether KeyPulse could really keep its files in this folder.

    Asked rather than assumed: on Windows a folder can exist and still refuse
    to be written to, and the answer decides where everything the program owns
    is going to live. The probe is made and removed under a unique name, so
    two copies starting at once cannot delete each other's.
    """
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle, probe = tempfile.mkstemp(prefix=f".{APP_NAME.lower()}-", suffix=".test", dir=folder)
        os.close(handle)
        os.unlink(probe)
    except OSError:
        return False
    return True


def _home_candidates() -> list[Path]:
    """Every folder KeyPulse has kept its files in, the one in use first.

    The working directory is on this list because it is where the earliest
    builds wrote, and it is the reason a wall of pictures could go blank
    overnight: Windows starts the app from a different working directory at
    boot than a double click gives it, so "snapshots" pointed somewhere else
    every time. D:/KeyPulse is here for the same reason -- one build filed
    everything into a folder of its own on the D: drive, which is nowhere the
    user put the program. Nothing below is relative any more: the list is kept
    only so files left in an older folder can be found and brought home.
    """
    homes = [_choose_home(), _program_dir(), Path("D:/") / APP_NAME]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        homes.append(Path(local) / APP_NAME)
    homes.append(Path.home() / f".{APP_NAME.lower()}")
    try:
        homes.append(Path.cwd())
    except OSError:
        pass
    unique: list[Path] = []
    for home in homes:
        if home not in unique:
            unique.append(home)
    return unique


def _choose_home() -> Path:
    """The folder KeyPulse keeps its files in: the one the program sits in.

    stats.json, settings.json and the snapshots folder all land beside
    KeyPulse.exe, where whoever ran it can find them. Nothing is filed into a
    folder of the program's own choosing on a drive the user never named:
    a copy of the program carries its own counts, and deleting the folder
    deletes all of it, which is what someone handed a program expects.

    This is the program's folder worked out from sys.executable, not the
    working directory. The two are not the same thing, and following the
    second is what once made a wall of pictures go blank overnight: Windows
    hands the app a different working directory at boot than a double click
    does, so a relative "snapshots" pointed somewhere new every start.

    A program that cannot write beside itself -- dropped into Program Files,
    run off a read-only share -- still has to start, so that one case falls
    back to the user's own AppData.
    """
    program = _program_dir()
    if _writable(program):
        return program
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


DATA_DIR = _choose_home()
STATS_PATH = DATA_DIR / "stats.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# The two things KeyPulse counts. The keyboard keeps the top level of
# stats.json it has always had; anything else lives under "devices", so a file
# written by an older build still loads and an older build still reads this one.
KEYBOARD_DEVICE = "keyboard"
GAMEPAD_DEVICE = "gamepad"
DEVICES = (KEYBOARD_DEVICE, GAMEPAD_DEVICE)

# One folder per device inside snapshots/, so the archive is two walls on disk
# the way it is two walls on screen, and a folder full of pictures is a folder
# of one device's pictures. The names are English and fixed: they are on disk,
# where the language the window is speaking has never reached.
DEVICE_FOLDER = {KEYBOARD_DEVICE: "keyboard", GAMEPAD_DEVICE: "gamepad"}


class DataFolderError(RuntimeError):
    """KeyPulse cannot use the folder it keeps everything in.

    Raised before there is a window, and shown by whoever catches it. So it
    carries the sentence as English plus what fills it, the way the hooks
    carry theirs, rather than as a finished string: the language was chosen
    before this could go wrong, and the box that reports it should speak it.
    """

    def __init__(self, folder: Path, reason: object) -> None:
        super().__init__(f"KeyPulse cannot use its folder {folder}: {reason}")
        self.message = "KeyPulse cannot use its folder {folder}."
        self.params = {"folder": folder}
        self.reason = str(reason)


def ensure_data_dir() -> Path:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise DataFolderError(DATA_DIR, error) from error
    return DATA_DIR


def snapshot_dir() -> Path:
    """The archive: one folder per device inside it, and nothing else."""
    return DATA_DIR / SNAPSHOT_DIR_NAME


def device_snapshot_dir(device: str) -> Path:
    """The folder one device's archived runs are filed into."""
    return snapshot_dir() / DEVICE_FOLDER.get(device, DEVICE_FOLDER[KEYBOARD_DEVICE])


def ensure_snapshot_dir(device: str | None = None) -> Path:
    """The archive folder, or one device's folder inside it, made if missing."""
    ensure_data_dir()
    directory = snapshot_dir() if device is None else device_snapshot_dir(device)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def current_snapshot_folders() -> list[Path]:
    """Where the archive in use is read from: each device's folder, then the
    archive folder itself, which is where every build before the folders put
    everything. A run is read out of the first folder it turns up in."""
    archive = snapshot_dir()
    return [archive / name for name in DEVICE_FOLDER.values()] + [archive]


def archive_device(path: Path) -> str | None:
    """Which device filed this run, or None if the file is not a run at all.

    An archive from before there was a second device names no device, and the
    keyboard is the one that filed it.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("kind") != "reset_snapshot":
        return None
    device = data.get("device")
    return device if device in DEVICES else KEYBOARD_DEVICE


def is_archive(path: Path) -> bool:
    """Whether this file is a run KeyPulse filed, rather than any other JSON."""
    return archive_device(path) is not None


def _move_run(source: Path, target: Path) -> bool:
    """Move one run -- the counts and the picture beside them -- in one piece.

    A run is two files under one name, so half a move is worse than none: a
    .json that has arrived without its .png hangs in the gallery as an exhibit
    with a missing picture. The picture goes first and is put back if the
    counts cannot follow it.
    """
    picture, moved = source.with_suffix(".png"), None
    if picture.exists():
        try:
            shutil.move(str(picture), str(target.with_suffix(".png")))
            moved = target.with_suffix(".png")
        except OSError:
            return False
    try:
        shutil.move(str(source), str(target))
    except OSError:
        if moved is not None:
            try:
                shutil.move(str(moved), str(picture))
            except OSError:
                pass
        return False
    return True


def file_loose_runs() -> list[Path]:
    """Move runs lying loose in the archive down into their device's folder.

    Every build before the folders wrote straight into snapshots/, so an
    archive that has been going a while is a single heap of files with two
    devices mixed through it. Each one names the device that filed it, which
    is all it takes to sort them; a name already taken in the folder below is
    left alone rather than overwritten.
    """
    archive = snapshot_dir()
    try:
        loose = sorted(archive.glob("keypulse*.json"))
    except OSError:
        return []
    filed: list[Path] = []
    for source in loose:
        device = archive_device(source)
        if device is None:
            continue
        target = device_snapshot_dir(device) / source.name
        if target.exists():
            continue
        try:
            ensure_snapshot_dir(device)
        except OSError:
            continue
        if _move_run(source, target):
            filed.append(target)
    return filed


def legacy_data_dirs() -> list[Path]:
    """The older homes, the one in use left out."""
    def settled(path: Path) -> Path:
        try:
            return path.resolve()
        except OSError:
            return path

    current = settled(DATA_DIR)
    older: list[Path] = []
    for home in _home_candidates():
        home = settled(home)
        if home != current and home not in older:
            older.append(home)
    return older


def adopt_orphaned_snapshots(sources: Iterable[Path] | None = None) -> list[Path]:
    """Bring runs filed into an older folder into the one in use.

    Moving the data folder used to take the whole gallery with it: the
    pictures were still on disk, just not where the wall was looking. Every
    run found in an older home is copied into the current archive, under the
    folder of the device that filed it -- a name already there is left alone,
    so this is safe to run at every start, never overwrites a picture, and
    never deletes the original. It is the reason the wall cannot go blank
    again when the folder moves.
    """
    homes = list(sources) if sources is not None else legacy_data_dirs()
    adopted: list[Path] = []
    for home in homes:
        archive = home / SNAPSHOT_DIR_NAME
        found: list[Path] = []
        for folder in [archive] + [archive / name for name in DEVICE_FOLDER.values()]:
            try:
                found += sorted(folder.glob("keypulse*.json"))
            except OSError:
                continue
        for source in found:
            device = archive_device(source)
            if device is None:
                continue
            target = device_snapshot_dir(device) / source.name
            if target.exists():
                continue
            try:
                ensure_snapshot_dir(device)
                shutil.copy2(source, target)
            except OSError:
                continue
            picture = source.with_suffix(".png")
            if picture.exists():
                try:
                    shutil.copy2(picture, target.with_suffix(".png"))
                except OSError:
                    pass
            adopted.append(target)
    return adopted


def adopt_orphaned_state() -> list[Path]:
    """Bring the counts and the settings home from an older folder.

    The archive can be copied file by file because every run is its own file.
    stats.json and settings.json are one live file each, so there is nothing
    to merge and only one question worth asking: which copy was written last.
    That one is the one the user was still using, and it is brought across
    only when it is newer than what the folder in use holds -- so this does
    nothing at all on the second start, and nothing ever on a fresh machine.
    """
    adopted: list[Path] = []
    for name in ("stats.json", "settings.json"):
        target = DATA_DIR / name
        newest, when = None, _written_at(target)
        for home in legacy_data_dirs():
            source = home / name
            stamp = _written_at(source)
            if stamp > when:
                newest, when = source, stamp
        if newest is None:
            continue
        try:
            ensure_data_dir()
            shutil.copy2(newest, target)
        except OSError:
            continue
        adopted.append(target)
    return adopted


def _written_at(path: Path) -> float:
    """When a file was last written, as a timestamp; 0.0 if it is not there."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def snapshot_folders() -> list[Path]:
    """Every folder KeyPulse would read an archived run out of, in use first.

    Each home is its two device folders plus the archive folder itself, which
    is where every build before the folders wrote.
    """
    folders: list[Path] = []
    for home in [DATA_DIR] + legacy_data_dirs():
        archive = home / SNAPSHOT_DIR_NAME
        folders += [archive / name for name in DEVICE_FOLDER.values()]
        folders.append(archive)
    return folders


def remove_snapshot(path: Path) -> list[tuple[Path, OSError]]:
    """Delete one archived run everywhere KeyPulse would find it again.

    The file name is the run: the counts and the picture beside them. Deleting
    only the copy the wall happened to read is not a deletion -- the same run
    can be sitting in a folder an older build used, and the next start adopts
    that one straight back, so the exhibit the user took down reappears. It
    has to go from every folder on the list at once.

    Returns what could not be deleted, so the caller can say which; a file
    that was not there in the first place is not a failure.
    """
    stem = path.stem
    beaten: list[tuple[Path, OSError]] = []
    seen: set[str] = set()
    for folder in [path.parent] + snapshot_folders():
        for suffix in (".json", ".png"):
            target = folder / f"{stem}{suffix}"
            key = str(target).casefold()
            if key in seen:
                continue
            seen.add(key)
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                beaten.append((target, error))
    return beaten


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else default.copy()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default.copy()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    ensure_data_dir()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _section(document: dict[str, Any], device: str) -> dict[str, Any]:
    """The part of stats.json one device owns."""
    if device == KEYBOARD_DEVICE:
        return document
    devices = document.get("devices")
    if not isinstance(devices, dict):
        return {}
    section = devices.get(device)
    return section if isinstance(section, dict) else {}


@dataclass
class StatsStore:
    counts: dict[str, int] = field(default_factory=dict)
    daily: dict[str, int] = field(default_factory=dict)
    total: int = 0
    dirty: bool = False
    device: str = KEYBOARD_DEVICE
    # When the run on screen began: the first press after the last reset.
    # None until that press lands, so a run is never dated before it started.
    started_at: str | None = None

    @staticmethod
    def _today_key() -> str:
        return date.today().isoformat()

    @classmethod
    def load(cls, device: str = KEYBOARD_DEVICE) -> "StatsStore":
        raw = _section(_read_json(STATS_PATH, {}), device)
        counts = {
            str(key): max(0, int(value))
            for key, value in raw.get("keys", {}).items()
            if isinstance(value, (int, float))
        }
        daily = {
            str(key): max(0, int(value))
            for key, value in raw.get("daily_totals", {}).items()
            if isinstance(value, (int, float))
        }
        started = raw.get("started_at")
        return cls(
            counts=counts,
            daily=daily,
            total=sum(counts.values()),
            device=device,
            started_at=started if isinstance(started, str) else None,
        )

    def record(self, key_id: str) -> int:
        if self.started_at is None:
            self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.counts[key_id] = self.counts.get(key_id, 0) + 1
        self.total += 1
        today = self._today_key()
        self.daily[today] = self.daily.get(today, 0) + 1
        self.dirty = True
        return self.counts[key_id]

    def count(self, key_id: str) -> int:
        return self.counts.get(key_id, 0)

    @property
    def today_total(self) -> int:
        return self.daily.get(self._today_key(), 0)

    @property
    def favorite(self) -> tuple[str, int] | None:
        if not self.counts:
            return None
        return max(self.counts.items(), key=lambda item: item[1])

    def archive(
        self,
        labels: dict[str, str] | None = None,
        moment: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Write the counts as they stand to their own file under snapshots/.

        The snapshot keeps the same shape as stats.json, so anything that
        already reads that file can read a snapshot too, plus a ranking that
        makes the archive worth opening on its own. Pass `moment` to stamp the
        picture of the same run with the time that named this file, and `extra`
        for anything only the caller knows -- the layout it was drawn in, say.
        """
        directory = ensure_snapshot_dir(self.device)
        labels = labels or {}
        moment = moment or datetime.now().astimezone()
        ranked = sorted(self.counts.items(), key=lambda item: (-item[1], item[0]))
        days = sorted(self.daily)
        payload = {
            "version": 1,
            "kind": "reset_snapshot",
            "device": self.device,
            # The two ends of the run this file closes: when its first press
            # landed, and when it was filed. The gallery dates an exhibit by
            # them; older files without a start fall back to the first day.
            "started_at": self.started_at,
            "archived_at": moment.isoformat(timespec="seconds"),
            "covers": {
                "first_day": days[0] if days else None,
                "last_day": days[-1] if days else None,
            },
            "total_keystrokes": self.total,
            "distinct_keys": len(self.counts),
            "ranking": [
                {"key": key_id, "label": labels.get(key_id, key_id), "count": count}
                for key_id, count in ranked
            ],
            "keys": dict(self.counts),
            "daily_totals": dict(self.daily),
            "privacy": "Only per-key counts are stored; typed text is never stored.",
        }
        payload.update(extra or {})
        # The keyboard keeps the plain name its earlier archives already use.
        tag = "" if self.device == KEYBOARD_DEVICE else f"-{self.device}"
        stem = f"keypulse{tag}-{moment:%Y-%m-%d_%H%M%S}"
        path = directory / f"{stem}.json"
        # Two resets inside the same second would otherwise overwrite each other.
        attempt = 2
        while path.exists():
            path = directory / f"{stem}-{attempt}.json"
            attempt += 1
        _write_json_atomic(path, payload)
        return path

    def reset(self) -> None:
        """Start counting from zero. Call archive() first if the old counts matter."""
        self.counts.clear()
        self.daily.clear()
        self.total = 0
        self.started_at = None
        self.dirty = True
        self.save(force=True)

    def save(self, force: bool = False) -> None:
        """Merge this device's counts into stats.json, leaving the other's alone.

        Both stores write the same file, so each one reads what is there and
        replaces only its own section. The write itself is atomic and the two
        saves run one after the other on the UI thread, so neither can land on
        a half-written file or clobber the other's numbers.
        """
        if not self.dirty and not force:
            return
        document = _read_json(STATS_PATH, {})
        document["version"] = 2
        document["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        document["privacy"] = "Only per-key counts are stored; typed text is never stored."
        if self.device == KEYBOARD_DEVICE:
            document["total_keystrokes"] = self.total
            document["keys"] = self.counts
            document["daily_totals"] = self.daily
            document["started_at"] = self.started_at
        else:
            devices = document.get("devices")
            if not isinstance(devices, dict):
                devices = {}
            devices[self.device] = {
                "total_presses": self.total,
                "keys": self.counts,
                "daily_totals": self.daily,
                "started_at": self.started_at,
            }
            document["devices"] = devices
        _write_json_atomic(STATS_PATH, document)
        self.dirty = False


# What KeyPulse is out of the box. The lighting starts off: it is the one
# thing here that draws while nothing is being pressed, and a first look at
# the app should be the board and its counts, not the light show -- the switch
# in the header turns it on and the choice sticks from then on.
DEFAULT_SETTINGS: dict[str, Any] = {
    "device": KEYBOARD_DEVICE,
    "layout": "full",
    "zoom": 78,
    "gamepad_model": "xbox",
    "gamepad_zoom": 130,
    "lighting": False,
    "gamepad_lighting": False,
    "close_to_tray": True,
    "tray_hint_shown": False,
    "language": "en",
}


class SettingsStore:
    def __init__(self, frozen: bool = False) -> None:
        # A frozen store still answers and still takes changes; it just never
        # writes them back, so a one-off run -- a screenshot, say -- cannot
        # leave its zoom or its chosen device behind in the real settings.
        self.frozen = frozen
        # Whether this is the first start on this machine. Anything KeyPulse
        # decides for the user rather than reads back -- counting from the
        # next login on -- is decided on that start alone, and written down
        # straight away, so switching it off afterwards is not undone by the
        # next start.
        try:
            self.first_run = not SETTINGS_PATH.exists()
        except OSError:
            self.first_run = False
        self.values = DEFAULT_SETTINGS.copy()
        self.values.update(_read_json(SETTINGS_PATH, DEFAULT_SETTINGS))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value
        self.save()

    def save(self) -> None:
        if self.frozen:
            return
        _write_json_atomic(SETTINGS_PATH, self.values)


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable)
        return f'"{executable}" --background'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.exists() else Path(sys.executable)
    script = Path(sys.argv[0]).resolve()
    return f'"{executable}" "{script}" --background'


def is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return value == _startup_command()
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows only.")
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
