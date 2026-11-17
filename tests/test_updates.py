from bluecenchchat.core import updates


def test_version_compare():
    assert updates.is_newer("v1.1.12", "1.1.0")
    assert updates.is_newer("1.2.0", "1.1.99")
    assert not updates.is_newer("1.1.0", "1.1.0")
    assert not updates.is_newer("v1.0.9", "1.1.0")
    assert updates.SETUP_URL.endswith("/releases/latest/download/BlueCenchChat-Setup.exe")
