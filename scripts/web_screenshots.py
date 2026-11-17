"""Screenshots of the Blue Cench Chat web app on watch, phone and tablet sizes, with real data.

    PLAYWRIGHT_BROWSERS_PATH=... python scripts/web_screenshots.py <out-folder>
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


async def main(out: Path) -> None:
    from playwright.async_api import async_playwright

    from bluecenchchat.backend.authentication import AuthService, RegistrationData
    from bluecenchchat.backend.database import Database
    from bluecenchchat.core.node import BlueCenchChatNode

    tmp = Path(tempfile.mkdtemp())
    os.environ["BLUECENCHCHAT_HOME"] = str(tmp / "home")
    port = random.randint(48000, 60000)
    nodes = {}
    for name, full in (("alice", "Alice Uwase"), ("bob", "Bob Mugisha"), ("carol", "Carol Ishimwe")):
        db = Database(tmp / f"{name}.db")
        acc, _, ident = AuthService(db).register(RegistrationData(
            full_name=full, username=name, email=f"{name}@example.com", password="Passw0rd!x", confirm_password="Passw0rd!x"))
        n = BlueCenchChatNode(db, acc.id, ident, beacon_port=port)
        (tmp / f"{name}_dl").mkdir()
        n.update_settings(download_dir=str(tmp / f"{name}_dl"))
        await n.start()
        nodes[name] = n
    a, b, c = nodes["alice"], nodes["bob"], nodes["carol"]

    async def until(pred, t=10):
        for _ in range(int(t / 0.05)):
            if pred():
                return
            await asyncio.sleep(0.05)

    ab = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    await a.connections.send_request(ab)
    await until(lambda: (x := b.repo.contact_by_peer(a.identity.user_id)) and x.status == "pending_in")
    ba = b.repo.contact_by_peer(a.identity.user_id).id
    await b.connections.accept(ba)
    await until(lambda: a.repo.contact(ab).status == "accepted")
    a.repo.set_contact(ab, verified=True)
    for who, cid, text in ((b, ba, "Are you at the library?"), (a, ab, "Yes, 2nd floor. Sending the slides now."),
                           (b, ba, "Got them, thanks! The demo works over Bluetooth too.")):
        await who.messaging.send_text(cid, text)
        await asyncio.sleep(0.2)
    f = tmp / "slides.pdf"
    f.write_bytes(os.urandom(900_000))
    t1 = await a.transfers.send_paths(ab, [str(f)])
    await until(lambda: b.repo.transfer(t1) is not None)
    await b.transfers.accept(t1)
    await until(lambda: a.repo.transfer(t1).status == "completed")
    v = tmp / "holiday-video.mp4"
    v.write_bytes(os.urandom(2_000_000))
    t2 = await b.transfers.send_paths(ba, [str(v)])
    await until(lambda: a.repo.transfer(t2) is not None)
    cc = await c.connections.connect(lan=("127.0.0.1", a.lan.port))
    await c.connections.send_request(cc, "Hi, can we connect?")
    await until(lambda: (x := a.repo.contact_by_peer(c.identity.user_id)) and x.status == "pending_in")
    # social demo data
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1080, 1080))
    d = ImageDraw.Draw(im)
    for y in range(1080):
        d.line([(0, y), (1080, y)], fill=(55 + y // 12, 151 - y // 20, 240 - y // 30))
    lg = Image.open(ROOT / "assets" / "logo" / "bluecenchchat.png").convert("RGBA").resize((520, 520))
    im.paste(lg, (280, 280), lg)
    bio = io.BytesIO()
    im.save(bio, "JPEG", quality=85)
    await a.social.follow(ab, True)
    await b.social.follow(ba, True)
    await b.social.set_note("Library till 6", "Calm Down - Rema")
    await a.social.set_note("Exams week!", "")
    pid = await b.social.create_post("Study corner - slides came over Wi-Fi in seconds", bio.getvalue(), "Essence - Wizkid")
    await until(lambda: a.social.post(pid) is not None)
    await a.social.toggle_like(pid)
    await a.social.add_comment(pid, "Nice setup!")
    await asyncio.sleep(2.5)
    await a.web.start(port=0)
    base = f"https://127.0.0.1:{a.web.port}/"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        sizes = {"watch": (300, 300, 2), "phone": (390, 844, 3), "tablet": (1024, 768, 2)}
        for kind, (w, hgt, dpr) in sizes.items():
            ctx = await browser.new_context(viewport={"width": w, "height": hgt}, device_scale_factor=dpr,
                                            ignore_https_errors=True, is_mobile=kind != "tablet", has_touch=True)
            page = await ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            await page.goto(base)
            await page.wait_for_selector(".code-input")
            if kind == "phone":
                await page.screenshot(path=str(out / f"web-{kind}-0-pair.png"))
            await page.fill(".code-input", a.web.current_code())
            await page.wait_for_selector(".nav")
            await asyncio.sleep(1.2)
            await page.screenshot(path=str(out / f"web-{kind}-1-home.png"))
            await page.click('.nav button[aria-label="Chats"]')
            await asyncio.sleep(0.6)
            await page.click(".row")
            await page.wait_for_selector(".b")
            await asyncio.sleep(0.8)
            await page.screenshot(path=str(out / f"web-{kind}-2-chat.png"))
            if kind == "phone":
                await page.fill("#composer", "Sent from my phone over Wi-Fi")
                await page.click(".send")
                await until(lambda: any(m.body == "Sent from my phone over Wi-Fi" for m in b.repo.messages(ba)))
                await asyncio.sleep(0.5)
                await page.screenshot(path=str(out / f"web-{kind}-3-sent.png"))
            if kind != "tablet":
                await page.click(".back")
            for i, tab in enumerate(("People", "Nearby", "Files", "Profile"), 4):
                if True:
                    await page.click(f'.nav button[aria-label="{tab}"]')
                    await asyncio.sleep(0.8)
                    if tab == "People":
                        await page.click("text=Requests")
                        await asyncio.sleep(0.6)
                    await page.screenshot(path=str(out / f"web-{kind}-{i}-{tab.lower()}.png"))
            print(kind, "errors:", errors or "none")
            await ctx.close()
        await browser.close()
    assert any(m.body == "Sent from my phone over Wi-Fi" for m in b.repo.messages(ba))
    for n in nodes.values():
        await n.stop()
    print("done")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "web-shots")
    out.mkdir(parents=True, exist_ok=True)
    asyncio.run(main(out))
