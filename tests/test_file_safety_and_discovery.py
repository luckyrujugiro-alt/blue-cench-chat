from pathlib import Path

import pytest

from bluecenchchat.core import crypto, file_safety
from bluecenchchat.core.transports.bluetooth import BleBeacon
from bluecenchchat.core.transfer_engine import expand_paths


@pytest.mark.parametrize("raw,expected", [
    ("report.pdf", "report.pdf"),
    ("../../Windows/System32/evil.dll", "Windows/System32/evil.dll"),
    ("C:\\Users\\x\\a.txt", "C_/Users/x/a.txt"),
    ("\\\\server\\share\\a.txt", "server/share/a.txt"),
    ("folder/../../a.txt", "folder/a.txt"),
    ("CON.txt", "_CON.txt"),
    ("bad<>:name?.txt", "bad___name_.txt"),
    ("trailing. ", "trailing"),
])
def test_sanitize(raw, expected):
    assert file_safety.sanitize_relative_path(raw).as_posix() == expected


def test_sanitize_rejects_empty():
    for raw in ("", "..", "/", "../.."):
        with pytest.raises(file_safety.UnsafePathError):
            file_safety.sanitize_relative_path(raw)


def test_safe_join_and_unique(tmp_path):
    p = file_safety.safe_join(tmp_path, Path("a/b.txt"))
    assert str(p).startswith(str(tmp_path.resolve()))
    p.parent.mkdir(parents=True)
    p.write_text("x")
    assert file_safety.unique_path(p).name == "b (1).txt"


def test_ble_payload_roundtrip():
    hint = crypto.identity_hint(crypto.Identity.generate().public_bytes)
    raw = BleBeacon.encode(hint, 50123, "192.168.137.1", 0x00AABBCCDDEE, True)
    assert len(raw) <= 24  # fits a legacy advertisement
    info = BleBeacon.decode(raw)
    assert info == {"hint": hint.hex(), "lan_ip": "192.168.137.1", "lan_port": 50123,
                    "bt_addr": 0x00AABBCCDDEE, "rfcomm": True}
    assert BleBeacon.decode(b"\x00" * len(raw)) is None


def test_expand_paths_folder(tmp_path):
    d = tmp_path / "Photos"
    (d / "sub").mkdir(parents=True)
    (d / "a.jpg").write_bytes(b"1")
    (d / "sub" / "b.jpg").write_bytes(b"22")
    files, label = expand_paths([str(d)])
    assert {f["path"] for f in files} == {"Photos/a.jpg", "Photos/sub/b.jpg"}
    assert label == "Photos (2 files)"
    with pytest.raises(ValueError):
        expand_paths([str(tmp_path / "missing")])
