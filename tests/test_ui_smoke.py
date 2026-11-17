"""Headless UI smoke test: every page builds and refreshes against a real node."""
import asyncio
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
