"""Renders every Blue Cench Chat screen with REAL data and saves screenshots.

Two real nodes (alice + bob) run in this process and talk over localhost TCP:
they connect, accept, chat and transfer files through the production code.
Then Alice's main window is opened offscreen and each page is captured.

    python scripts/ui_screenshots.py <output-folder> [dark|light]
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


async def scenario(out: Path, mode: str) -> None:
    from PySide6.QtWidgets import QApplication

    from bluecenchchat.backend.authentication import AuthService, RegistrationData
    from bluecenchchat.backend.database import Database
    from bluecenchchat.core.node import BlueCenchChatNode
    from bluecenchchat.ui import icons, theme
    from bluecenchchat.ui.auth_window import AuthWindow
    from bluecenchchat.ui.main_window import MainWindow

    tmp = Path(tempfile.mkdtemp())
    os.environ["BLUECENCHCHAT_HOME"] = str(tmp / "home")
    port = random.randint(48000, 60000)
    nodes = {}
    for name, full in (("alice", "Alice Uwase"), ("bob", "Bob Mugisha")):
        db = Database(tmp / f"{name}.db")
        acc, _, ident = AuthService(db).register(RegistrationData(
            full_name=full, username=name, email=f"{name}@example.com", password="Passw0rd!x",
            confirm_password="Passw0rd!x"))
        n = BlueCenchChatNode(db, acc.id, ident, beacon_port=port)
        (tmp / f"{name}_dl").mkdir()
        n.update_settings(download_dir=str(tmp / f"{name}_dl"), onboarded=True, theme=mode)
        n.repo.update_profile(about="Software developer in Kigali" if name == "alice" else "Designer - shares big files")
        await n.start()
        nodes[name] = n
    a, b = nodes["alice"], nodes["bob"]

    async def until(pred, t=10):
        for _ in range(int(t / 0.05)):
            if pred():
                return
            await asyncio.sleep(0.05)

    ab = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    await a.connections.send_request(ab, "Hi Bob, it's Alice from the workshop")
    await until(lambda: (c := b.repo.contact_by_peer(a.identity.user_id)) and c.status == "pending_in")
    ba = b.repo.contact_by_peer(a.identity.user_id).id
    await b.connections.accept(ba)
    await until(lambda: a.repo.contact(ab).status == "accepted")
    b.repo.set_contact(ba, verified=True)
    a.repo.set_contact(ab, verified=True)
    for who, cid, text in ((a, ab, "Hi Bob! Did the Bluetooth pairing work on your laptop?"),
                           (b, ba, "Yes - paired in Windows settings and Blue Cench Chat found the service right away."),
                           (a, ab, "Great. I'm sending the project folder and the demo video now."),
                           (b, ba, "Perfect, I'm on the hotspot so it should be fast.")):
        await who.messaging.send_text(cid, text)
        await asyncio.sleep(0.15)
    src = tmp / "src"
    (src / "Project Files" / "docs").mkdir(parents=True)
    (src / "Project Files" / "docs" / "spec.pdf").write_bytes(os.urandom(800_000))
    (src / "Project Files" / "logo.png").write_bytes((ROOT / "assets" / "logo" / "bluecenchchat.png").read_bytes())
    (src / "demo-video.mp4").write_bytes(os.urandom(6_000_000))
    t1 = await a.transfers.send_paths(ab, [str(src / "Project Files")])
    await until(lambda: b.repo.transfer(t1) is not None)
    await b.transfers.accept(t1)
    await until(lambda: a.repo.transfer(t1).status == "completed")
    (src / "photo.png").write_bytes((ROOT / "assets" / "logo" / "bluecenchchat.png").read_bytes())
    t3 = await b.transfers.send_paths(ba, [str(src / "photo.png")])
    await until(lambda: a.repo.transfer(t3) is not None)
    await a.transfers.accept(t3)
    await until(lambda: a.repo.transfer(t3).status == "completed")
    t2 = await a.transfers.send_paths(ab, [str(src / "demo-video.mp4")])
    await until(lambda: b.repo.transfer(t2) is not None)
    # a third person asks to connect to Alice
    db3 = Database(tmp / "carol.db")
    acc3, _, id3 = AuthService(db3).register(RegistrationData(
        full_name="Carol Ishimwe", username="carol", email="carol@example.com", password="Passw0rd!x",
        confirm_password="Passw0rd!x"))
    c = BlueCenchChatNode(db3, acc3.id, id3, beacon_port=port)
    await c.start()
    cc = await c.connections.connect(lan=("127.0.0.1", a.lan.port))
    await c.connections.send_request(cc, "Can I join the file share?")
    await until(lambda: a.repo.contact_by_peer(c.identity.user_id) is not None
                and a.repo.contact_by_peer(c.identity.user_id).status == "pending_in")
    await asyncio.sleep(2.5)  # let LAN presence beacons arrive

    app = QApplication.instance()
    theme.set_theme(mode)
    icons.clear_cache()
    app.setStyleSheet(theme.stylesheet())
    aw = AuthWindow(AuthService(Database(tmp / "fresh.db")))
    aw.resize(1200, 760)
    aw.show()
    await asyncio.sleep(0.3)
    aw.grab().save(str(out / f"{mode}-00-welcome.png"))
    aw.go(aw.register)
    await asyncio.sleep(0.3)
    aw.grab().save(str(out / f"{mode}-00b-register.png"))
    aw.close()

    win = MainWindow(a)
    win.resize(int(os.environ.get("SHOT_W","1440")), int(os.environ.get("SHOT_H","900")))
    win.show()
    await asyncio.sleep(0.5)
    a.update_settings(web_enabled=True)
    await a.web.start(port=0)
    pages = ["dashboard", "discover", "connections", "messages", "transfers", "devices", "web", "history",
             "notifications", "profile", "security", "settings", "help"]
    for i, key in enumerate(pages, 1):
        if key == "messages":
            win.open_chat(ab)
        elif key == "connections":
            win.navigate(key)
            win.pages["connections"].show_requests()
        else:
            win.navigate(key)
        if key == "devices":
            win.pages["devices"].run_test()
        await asyncio.sleep(0.8)
        win.grab().save(str(out / f"{mode}-{i:02d}-{key}.png"))
    print("screenshots written to", out)
    win.teardown()
    for n in (a, b, c):
        await n.stop()


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screens")
    mode = sys.argv[2] if len(sys.argv) > 2 else "dark"
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication
    import qasync

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    with loop:
        loop.run_until_complete(scenario(out, mode))


if __name__ == "__main__":
    main()
