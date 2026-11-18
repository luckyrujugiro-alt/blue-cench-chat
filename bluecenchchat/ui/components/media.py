"""Play a short audio clip (a note's song or a preview) - one at a time."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

_player = None
_output = None


def _ext(data: bytes) -> str:
    if data[4:8] == b"ftyp":
        return ".m4a"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:4] == b"fLaC":
        return ".flac"
    return ".mp3"


def play_clip(data: bytes | None) -> bool:
    """Plays the clip; calling again with the same clip stops it (toggle). Returns True if now playing."""
    global _player, _output
    if not data or os.environ.get("BLUECENCHCHAT_NO_MEDIA"):
        return False
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except Exception:
        return False
    path = Path(tempfile.gettempdir()) / f"bcc-clip-{hashlib.sha1(data).hexdigest()[:16]}{_ext(data)}"
    if not path.exists():
        path.write_bytes(data)
    if _player is None:
        _player = QMediaPlayer()
        _output = QAudioOutput()
        _output.setVolume(0.9)
        _player.setAudioOutput(_output)
    url = QUrl.fromLocalFile(str(path))
    if _player.source() == url and _player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
        _player.stop()
        return False
    _player.setSource(url)
    _player.play()
    return True


def stop() -> None:
    if _player is not None:
        _player.stop()
