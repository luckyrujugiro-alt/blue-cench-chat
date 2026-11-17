# PyInstaller build definition. Run from the project root:  pyinstaller bluecenchchat.spec --noconfirm
from PyInstaller.utils.hooks import collect_submodules

hidden = ["argon2", "sqlalchemy.dialects.sqlite", "qasync", "PySide6.QtSvg", "PySide6.QtNetwork", "qrcode", "PIL"]
hidden += collect_submodules("uvicorn") + ["multipart", "python_multipart", "websockets", "fastapi"]
try:
    hidden += collect_submodules("winrt")
except Exception:
    pass

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("assets", "assets"), ("bluecenchchat/web/static", "bluecenchchat/web/static")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BlueCenchChat",
    console=False,
    icon="assets/logo/bluecenchchat.ico",
    version="installer/version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="BlueCenchChat")
