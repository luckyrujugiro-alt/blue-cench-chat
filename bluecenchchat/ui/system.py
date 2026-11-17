"""Small OS integration helpers (Windows-first, safe elsewhere)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def open_path(path: str | Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_file(path: str | Path) -> None:
    p = Path(path)
    if sys.platform == "win32" and p.exists():
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        open_path(p.parent if p.is_file() else p)


def open_bluetooth_settings() -> bool:
    if sys.platform == "win32":
        os.startfile("ms-settings:bluetooth")  # type: ignore[attr-defined]
        return True
    return False


def open_hotspot_settings() -> bool:
    if sys.platform == "win32":
        os.startfile("ms-settings:network-mobilehotspot")  # type: ignore[attr-defined]
        return True
    return False


def set_start_with_windows(enabled: bool) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    exe = sys.executable if getattr(sys, "frozen", False) else None
    if exe is None:
        return False  # only the installed .exe registers itself
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "Blue Cench Chat", 0, winreg.REG_SZ, f'"{exe}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, "Blue Cench Chat")
            except FileNotFoundError:
                pass
    return True


def file_icon_name(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".svg"}:
        return "image"
    if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"}:
        return "video"
    if ext in {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}:
        return "music"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "file-archive"
    if ext in {".exe", ".msi", ".apk"}:
        return "package"
    if ext in {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".md"}:
        return "file-text"
    if name.endswith(")") and "files" in name:
        return "folder"
    return "file"


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
