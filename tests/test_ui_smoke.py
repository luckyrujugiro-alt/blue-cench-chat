"""Headless UI smoke test: every page builds and refreshes against a real node."""
import asyncio
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BLUECENCHCHAT_NO_MEDIA", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from .conftest import connect_and_accept, wait_for  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


async def test_all_pages_render(qapp, pair, tmp_path):
    from bluecenchchat.ui import theme
    from bluecenchchat.ui.main_window import NAV, MainWindow

    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await a.messaging.send_text(ab, "hello from the smoke test")
    f = tmp_path / "x.bin"
    f.write_bytes(b"x" * 5000)
    tid = await a.transfers.send_paths(ab, [str(f)])
    await wait_for(lambda: b.repo.transfer(tid) is not None)
    qapp.setStyleSheet(theme.stylesheet())
    win = MainWindow(a)
    win.show()
    for key, *_ in NAV:
        win.navigate(key)
        await asyncio.sleep(0.05)
        assert win.stack.currentWidget() is win.pages[key]
    win.open_chat(ab)
    chat = win.pages["messages"].chat
    assert chat is not None and chat.order
    chat.edit.setPlainText("typed in the UI")
    chat.send()
    await wait_for(lambda: any(m.body == "typed in the UI" for m in b.repo.messages(ba)))
    # theme switch rebuilds the whole window without errors
    a.update_settings(theme="light")
    win.apply_theme(rebuild=True)
    win.navigate("settings")
    win.teardown()
    win.close()


async def test_social_and_call_ui(qapp, pair, monkeypatch):
    """Feed cards, profiles, verification page, a voice call window and the theme toggle."""
    from bluecenchchat.ui import theme
    from bluecenchchat.ui.components.social import CommentsDialog, PostCard, ProfileDialog
    from bluecenchchat.ui.main_window import MainWindow

    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await a.social.follow(ab, True)
    await b.social.follow(ba, True)
    pid = await b.social.create_post("hello feed", None, "Song - Artist")
    await wait_for(lambda: a.social.post(pid) is not None)
    qapp.setStyleSheet(theme.stylesheet())
    win = MainWindow(a)
    win.show()
    win.navigate("home")
    await asyncio.sleep(0.3)
    cards = win.pages["home"].findChildren(PostCard)
    assert any(c.post_id == pid for c in cards)
    # dialogs build (shown non-modally so the test doesn't block)
    for dlg in (ProfileDialog(win, ab), CommentsDialog(win, pid)):
        dlg.show()
        await asyncio.sleep(0.05)
        dlg.close()
    win.navigate("profile")
    win.navigate("verify")
    # call: Bob rings Alice -> Alice's call window appears; she answers; Bob hangs up
    await b.calls.start(ba, video=False)
    await wait_for(lambda: win.call_window is not None)
    assert win.call_window.call.state == "ringing"
    await a.calls.accept()
    await wait_for(lambda: b.calls.current.state == "active")
    await b.calls.hangup()
    await wait_for(lambda: a.calls.current.state == "ended")
    await wait_for(lambda: any(m.kind == "call" for m in a.repo.messages(ab)))
    win.open_chat(ab)
    await asyncio.sleep(0.1)
    # Ctrl+D path
    win.toggle_theme()
    assert a.settings.get("theme") == "dark"
    win.toggle_theme()
    assert a.settings.get("theme") == "midnight"
    win.toggle_theme()
    assert a.settings.get("theme") == "light"
    win.teardown()
    win.close()
