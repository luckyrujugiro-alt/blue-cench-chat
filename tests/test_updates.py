from bluecenchchat.core import updates


def test_version_compare():
    assert updates.is_newer("v1.1.12", "1.1.0")
    assert updates.is_newer("1.2.0", "1.1.99")
    assert not updates.is_newer("1.1.0", "1.1.0")
    assert not updates.is_newer("v1.0.9", "1.1.0")
    assert updates.SETUP_URL.endswith("/releases/latest/download/BlueCenchChat-Setup.exe")


def test_download_verifies_fingerprint(tmp_path, monkeypatch):
    import hashlib
    import io

    import pytest

    blob = b"MZ" + b"x" * 1_500_000
    good = hashlib.sha256(blob).hexdigest()

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(blob))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **k: Resp(blob))
    seen = []
    monkeypatch.setattr(updates, "expected_sha256", lambda: good)
    out = tmp_path / "Setup.exe"
    assert updates.download_installer(out, lambda d, t: seen.append((d, t))) == good
    assert out.read_bytes() == blob and seen[-1] == (len(blob), len(blob))
    # damaged download is rejected and removed
    monkeypatch.setattr(updates, "expected_sha256", lambda: "0" * 64)
    out2 = tmp_path / "Setup2.exe"
    with pytest.raises(RuntimeError, match="damaged"):
        updates.download_installer(out2)
    assert not out2.exists() and not (tmp_path / "Setup2.exe.part").exists()
