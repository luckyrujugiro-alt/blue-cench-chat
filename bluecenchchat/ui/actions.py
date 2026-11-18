"""User actions shared by several pages."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFileDialog, QMenu

from . import icons
from .dialogs.common import ConnectDialog, VerifyDialog, ask_text, confirm


def connect_peer(win, peer, via: str | None = None) -> None:
    """Connect to a discovered peer and, if needed, send a connection request.

    via: "lan" (same Wi-Fi), "bt" (Bluetooth) or None (best available)."""
    node, bridge = win.node, win.bridge
    lan = (peer.lan_ip, peer.lan_port) if peer.lan_ip and peer.lan_port else None
    bt = peer.bt_addr
    if via == "lan":
        bt = None
    elif via == "bt":
        lan = None
    if not lan and not bt:
        win.toast("Not reachable that way yet. Keep scanning, or try the other button.", "warning")
        return
    prefer = "lan" if lan else "rfcomm"
    via = "local network" if lan else "Bluetooth RFCOMM"
    win.toast(f"Connecting to {peer.display_name()} over {via}...")

    async def go():
        cid = await node.connections.connect(lan=lan, bt_addr=bt, prefer=prefer,
                                             expect_user_id=peer.user_id or None)
        c = node.repo.contact(cid)
        if c.status != "accepted":
            await node.connections.send_request(cid, "")
        return cid

    def done(cid):
        c = node.repo.contact(cid)
        if c.status == "accepted":
            win.toast(f"Connected to {c.name}", "success")
        else:
            win.toast(f"Request sent to {c.name}. Waiting for them to accept.", "success")

    bridge.run(go(), done, lambda e: win.toast(f"Could not connect: {e}", "error"))


def connect_dialog(win) -> None:
    d = ConnectDialog(win)
    if d.exec() != QDialog.DialogCode.Accepted:
        return
    node, bridge = win.node, win.bridge

    async def go():
        if d.result_kind == "code":
            cid = await node.connect_with_code(d.value)
        else:
            cid = await node.connections.connect(lan=d.value)
        c = node.repo.contact(cid)
        if c.status != "accepted":
            await node.connections.send_request(cid, "")
        return cid

    bridge.run(go(), lambda cid: win.toast(f"Connected to {node.repo.contact(cid).name}", "success"),
               lambda e: win.toast(f"Could not connect: {e}", "error"))


def send_files(win, contact_id: int, folder: bool = False) -> None:
    if folder:
        path = QFileDialog.getExistingDirectory(win, "Choose a folder to send")
        paths = [path] if path else []
    else:
        paths, _ = QFileDialog.getOpenFileNames(win, "Choose files to send")
    if paths:
        send_paths(win, contact_id, paths)


def send_paths(win, contact_id: int, paths: list[str]) -> None:
    node = win.node
    if node.low_battery():
        win.toast("Battery below 20% - large transfers drain power. Plug in if you can.", "warning")
    win.bridge.run(node.transfers.send_paths(contact_id, paths),
                   lambda _tid: win.toast("Transfer prepared - waiting for the receiver to accept", "success"),
                   lambda e: win.toast(str(e), "error"))


def toggle_tick(win, contact_id: int, after=None) -> None:
    """Official account only: give or remove someone's blue tick in one click."""
    node = win.node
    c = node.repo.contact(contact_id)
    if c is None or not node.social.is_admin():
        return
    if node.social.is_verified(c):
        if not confirm(win, f"Remove {c.name}'s blue tick?", "The removal spreads to every device that meets yours.",
                       "Remove", True):
            return
        win.bridge.run(node.social.revoke_tick(c.peer_user_id),
                       lambda _r: (win.toast(f"Removed {c.name}'s blue tick"), after and after()))
    else:
        win.bridge.run(node.social.grant_tick(c.peer_user_id),
                       lambda _r: (win.toast(f"{c.name} is verified", "success"), after and after()))


SUSPEND_CHOICES = [("4 hours", 4), ("1 day", 24), ("7 days", 24 * 7), ("30 days", 24 * 30), ("Forever", None)]


def fill_suspend_menu(win, menu: QMenu, uid: str, name: str) -> None:
    """Official account only: suspend for a while / forever, or lift it."""
    node = win.node
    cur = node.social.suspension(uid)
    sub = menu.addMenu(icons.plain("ban", 16, "#F4212E"), "Suspend" if not cur else "Suspended - change")
    for title, hours in SUSPEND_CHOICES:
        sub.addAction(title, lambda h=hours, t=title: _do_suspend(win, uid, name, h, t))
    if cur:
        sub.addSeparator()
        sub.addAction(icons.plain("rotate-cw", 16), "Lift suspension", lambda: _do_suspend(win, uid, name, 0, ""))


def _do_suspend(win, uid: str, name: str, hours, title: str) -> None:
    from PySide6.QtWidgets import QInputDialog
    if hours == 0:
        win.bridge.run(win.node.social.suspend(uid, 0), lambda _r: win.toast(f"{name} can use Blue Cench Chat again"))
        return
    reason, ok = QInputDialog.getText(win, f"Suspend {name}", f"Suspend {name} for {title.lower()}.\n"
                                      "Reason (they will see it):")
    if not ok:
        return
    win.bridge.run(win.node.social.suspend(uid, hours, reason.strip()),
                   lambda _r: win.toast(f"{name} is suspended ({title.lower()})", "warning"))


def contact_menu(win, contact, parent_widget) -> QMenu:
    node, bridge = win.node, win.bridge
    m = QMenu(parent_widget)
    online = node.connections.is_online(contact.id)
    if contact.status == "accepted":
        m.addAction(icons.plain("message-square", 16), "Message", lambda: win.open_chat(contact.id))
        m.addAction(icons.plain("paperclip", 16), "Send files...", lambda: send_files(win, contact.id))
        m.addAction(icons.plain("folder", 16), "Send a folder...", lambda: send_files(win, contact.id, True))
        m.addAction(icons.plain("badge-check", 16), "Verify safety number...",
                    lambda: VerifyDialog(win, node, node.repo.contact(contact.id)).exec())
        if node.social.is_admin():
            fill_suspend_menu(win, m, contact.peer_user_id, contact.name)
            ticked = node.social.is_verified(contact)
            m.addAction(icons.plain("badge-check", 16, "#0095F6"),
                        "Remove blue tick" if ticked else "Give blue tick",
                        lambda: toggle_tick(win, contact.id))
        fav = "Remove from favorites" if contact.favorite else "Add to favorites"
        m.addAction(icons.plain("star", 16), fav, lambda: (node.repo.set_contact(contact.id, favorite=not contact.favorite),
                                                          node.bus.emit("contacts")))
        m.addSeparator()
    if online:
        m.addAction(icons.plain("unlink", 16), "Disconnect", lambda: bridge.run(node.connections.disconnect(contact.id)))
    if contact.status == "blocked":
        m.addAction(icons.plain("user-check", 16), "Unblock", lambda: node.connections.unblock(contact.id))
    else:
        def _block():
            if confirm(win, f"Block {contact.name}?", "They will be disconnected, pending transfers are cancelled "
                       "and future connections from this identity are refused.", "Block", danger=True):
                bridge.run(node.connections.block(contact.id), lambda _: win.toast(f"{contact.name} blocked", "success"))
        m.addAction(icons.plain("ban", 16), "Block", _block)

    def _report():
        reason = ask_text(win, "Report suspicious activity",
                          f"Describe what happened with {contact.name} ({contact.peer_user_id}). The report is "
                          "stored in your local security log; consider blocking as well.", "What happened?")
        if reason:
            node.repo.report(contact.peer_user_id, reason)
            node.repo.log("security", f"Reported {contact.name} ({contact.peer_user_id}): {reason[:120]}")
            win.toast("Report saved to your security log", "success")

    m.addAction(icons.plain("flag", 16), "Report suspicious activity...", _report)

    def _remove():
        if confirm(win, f"Remove {contact.name}?", "The contact, conversation and transfer history with this "
                   "person are deleted from this PC.", "Remove", danger=True):
            async def go():
                await node.connections.disconnect(contact.id)
                node.repo.remove_contact(contact.id)
                node.discovery.refresh_contact_hints()
                node.bus.emit("contacts")
            bridge.run(go())

    m.addAction(icons.plain("trash-2", 16), "Remove contact", _remove)
    return m
