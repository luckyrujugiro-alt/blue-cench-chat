"""Safe handling of file names and paths coming from remote peers."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_COMPONENT = 150
MAX_DEPTH = 24


class UnsafePathError(ValueError):
    pass


def sanitize_component(name: str) -> str:
    name = _BAD_CHARS.sub("_", name)
    name = name.strip().rstrip(". ")
    if not name or name in (".", ".."):
        return ""
    stem = name.split(".")[0].upper()
    if stem in _RESERVED:
        name = "_" + name
    if len(name) > MAX_COMPONENT:
        root, ext = os.path.splitext(name)
        name = root[: MAX_COMPONENT - len(ext[:20])] + ext[:20]
    return name


def sanitize_relative_path(rel: str) -> Path:
    """Turn an untrusted relative path into a safe relative Path.

    Absolute paths, drive letters, UNC prefixes and ``..`` traversal are all
    neutralised; the result always stays inside the destination folder.
    """
    if not isinstance(rel, str) or not rel or len(rel) > 1024:
        raise UnsafePathError("invalid file name")
    parts = [p for p in re.split(r"[\\/]+", rel) if p]
    clean = [c for c in (sanitize_component(p) for p in parts) if c]
    if not clean:
        raise UnsafePathError("empty file name")
    if len(clean) > MAX_DEPTH:
        raise UnsafePathError("folder structure too deep")
    return Path(*clean)


def safe_join(root: Path, rel: Path) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise UnsafePathError("path escapes destination folder")
    return target


def unique_path(path: Path) -> Path:
    """'report.pdf' -> 'report (1).pdf' if it already exists."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10_000):
        cand = path.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
    raise UnsafePathError("too many files with the same name")


def mark_from_other_device(path: Path) -> None:
    """Attach the Windows 'Mark of the Web' so SmartScreen and Office treat
    received executables/documents as untrusted (Protected View, warnings)."""
    if sys.platform != "win32":
        return
    try:
        with open(str(path) + ":Zone.Identifier", "w", encoding="ascii") as fh:
            fh.write("[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=bluecenchchat://peer\r\n")
    except OSError:
        pass


RISKY_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".com", ".jar", ".lnk", ".reg", ".hta"}


def is_risky(name: str) -> bool:
    return Path(name).suffix.lower() in RISKY_EXTENSIONS
