from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from ... import config
from .. import actions, icons, system, theme
from ..components.transfer_row import STATUS_TEXT, TransferRow
from ..components.widgets import (
    BarChart,
    Card,
    EmptyState,
    Page,
    SearchBox,
    StatCard,
    button,
    clear_layout,
    human_size,
    icon_label,
    label,
)
from ..dialogs.common import confirm

LIVE = ("offered", "active", "paused", "waiting", "preparing", "queued", "interrupted")


class DropZone(QFrame):
    def __init__(self, on_paths) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.on_paths = on_paths
        self.setMinimumHeight(170)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)
        p = theme.palette()
        ic = icon_label("upload-cloud", 40, p.primary_hover)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label("Drag and drop files or folders here", "h3")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = label("Documents, images, videos, music, archives, applications and whole folders. "
                  "Every file is verified with SHA-256 on arrival.", "muted", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)
        row = QHBoxLayout()
        row.addStretch(1)
        self.b_files = button("Select files", "file", "primary")
        self.b_folder = button("Select folder", "folder")
        row.addWidget(self.b_files)
        row.addWidget(self.b_folder)
        row.addStretch(1)
        lay.addLayout(row)

    def _active(self, on: bool) -> None:
        self.setProperty("active", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._active(True)

    def dragLeaveEvent(self, _e) -> None:
        self._active(False)

    def dropEvent(self, e) -> None:
        self._active(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.on_paths(paths)


class TransfersPage(Page):
    def __init__(self, win) -> None:
        super().__init__("File Transfers", "Send files and folders to your connections. Large files go fastest "
                         "over the local network; Bluetooth RFCOMM is used when no network is shared.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()
        top = QHBoxLayout()
        top.setSpacing(14)
        send = Card("Send", "upload")
        rr = QHBoxLayout()
        rr.addWidget(label("Recipient", "muted"))
        self.recipient = QComboBox()
        self.recipient.setMinimumWidth(260)
        rr.addWidget(self.recipient, 1)
        send.add(rr)
        self.route = label("", "faint", wrap=True)
        send.add(self.route)
        self.drop = DropZone(self._send)
        send.add(self.drop)
        self.drop.b_files.clicked.connect(lambda: self._pick(False))
        self.drop.b_folder.clicked.connect(lambda: self._pick(True))
        self.recipient.currentIndexChanged.connect(lambda _i: self._update_route())
        top.addWidget(send, 3)
        store = Card("Received files", "hard-drive")
        self.dl_path = label("", "mono", wrap=True)
        self.dl_free = label("", "muted")
        store.add(self.dl_path)
        store.add(self.dl_free)
        ob = button("Open folder", "folder-open")
        ob.clicked.connect(lambda: system.open_path(self._dl()))
        ch = button("Change location", "square-pen")
        ch.clicked.connect(self._change_dl)
        store.add(ob)
        store.add(ch)
        store.body.addStretch(1)
        top.addWidget(store, 1)
        self.content.addLayout(top)

        head = QHBoxLayout()
        head.addWidget(label("Transfer queue", "h2"))
        head.addStretch(1)
        self.content.addLayout(head)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        self.content.addLayout(self.list)
        self.content.addStretch(1)
        self.rows: dict[str, TransferRow] = {}
        self.bridge.transfer_changed.connect(self._on_transfer)
        self.bridge.transfer_offer.connect(lambda _t: self.refresh())
        self.bridge.contacts_changed.connect(self._fill_recipients)
        self.bridge.session_changed.connect(lambda *_: self._fill_recipients())
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._tick_rows)
        self._tick.start(500)
        self._fill_recipients()
        self.refresh()

    def _dl(self) -> Path:
        return Path(self.node.settings.get("download_dir") or config.default_download_dir())

    def _change_dl(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose download folder", str(self._dl()))
        if d:
            self.node.update_settings(download_dir=d)
            self.refresh()

    def select_contact(self, cid: int) -> None:
        i = self.recipient.findData(cid)
        if i >= 0:
            self.recipient.setCurrentIndex(i)

    def _fill_recipients(self) -> None:
        cur = self.recipient.currentData()
        self.recipient.blockSignals(True)
        self.recipient.clear()
        for c in self.node.repo.contacts(("accepted",)):
            online = self.node.connections.is_online(c.id)
            self.recipient.addItem(icons.plain("user", 16, theme.palette().success if online else theme.palette().faint),
                                   f"{c.name}  -  {'online' if online else 'offline (queued)'}", c.id)
        if cur is not None:
            i = self.recipient.findData(cur)
            if i >= 0:
                self.recipient.setCurrentIndex(i)
        self.recipient.blockSignals(False)
        self._update_route()

    def _update_route(self) -> None:
        cid = self.recipient.currentData()
        if cid is None:
            self.route.setText("Accept a connection first - files can only be sent to accepted contacts.")
            self.drop.setEnabled(False)
            return
        self.drop.setEnabled(True)
        s = self.node.connections.session_for_contact(cid)
        if s is None:
            self.route.setText("Offline: the transfer is prepared now and offered automatically when the "
                               "contact reconnects.")
        elif s.transport == "rfcomm":
            self.route.setText("Transport: Bluetooth RFCOMM (about 0.05-0.25 MB/s). For large files join the same "
                               "Wi-Fi or Mobile Hotspot - Blue Cench Chat will use the faster link next time you connect.")
        else:
            self.route.setText(f"Transport: {self.node.transport_label(s.transport)} - fast direct link, "
                               "no internet involved.")

    def _pick(self, folder: bool) -> None:
        cid = self.recipient.currentData()
        if cid is not None:
            actions.send_files(self.win, cid, folder)

    def _send(self, paths) -> None:
        cid = self.recipient.currentData()
        if cid is None:
            self.win.toast("Choose a recipient first", "warning")
            return
        actions.send_paths(self.win, cid, paths)

    def _on_transfer(self, tid: str) -> None:
        if tid in self.rows:
            self.rows[tid].refresh()
        elif self.isVisible():
            self.refresh()

    def _tick_rows(self) -> None:
        if not self.isVisible():
            return
        for tid, r in self.rows.items():
            if tid in self.node.transfers.progress:
                r.refresh()

    def on_show(self) -> None:
        self._fill_recipients()
        self.refresh()

    def refresh(self) -> None:
        dl = self._dl()
        self.dl_path.setText(str(dl))
        try:
            probe = dl if dl.exists() else Path(dl.anchor or Path.home())
            self.dl_free.setText(f"{human_size(shutil.disk_usage(probe).free)} free")
        except OSError:
            self.dl_free.setText("Folder unavailable")
        clear_layout(self.list)
        self.rows = {}
        items = self.node.repo.transfers(LIVE)
        recent = [t for t in self.node.repo.transfers(("completed", "failed", "cancelled", "rejected"), limit=5)
                  if time.time() - (t.finished_at or t.created_at) < 3600]
        items = sorted(items, key=lambda t: (t.status != "offered", -t.created_at)) + recent
        if not items:
            self.list.addWidget(EmptyState("arrow-left-right", "No transfers in progress",
                                           "Drop files above to send them. Finished transfers move to Transfer History."))
            return
        for t in items:
            r = TransferRow(self.bridge, t.id)
            self.rows[t.id] = r
            self.list.addWidget(r)


class HistoryPage(Page):
    FILTERS = ["All", "Received", "Sent", "Failed"]

    def __init__(self, win) -> None:
        super().__init__("Transfer History", "Every file you have sent or received, with verification results.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.s_in = StatCard("download", "Received", "success")
        self.s_out = StatCard("upload", "Sent", "warning")
        self.s_ok = StatCard("shield-check", "Success rate", "cyan")
        for w in (self.s_in, self.s_out, self.s_ok):
            stats.addWidget(w)
        self.content.addLayout(stats)
        chart = Card("Data moved per day - last 14 days", "chart-column")
        self.chart = BarChart()
        chart.add(self.chart)
        self.content.addWidget(chart)
        bar = QHBoxLayout()
        self.tabs = QTabBar()
        for f in self.FILTERS:
            self.tabs.addTab(f)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.tabs)
        bar.addStretch(1)
        self.search = SearchBox("Search files or contacts")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search)
        clr = button("Clear finished", "trash-2", "ghost")
        clr.clicked.connect(self._clear)
        bar.addWidget(clr)
        self.content.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Contact", "Direction", "Size", "Transport", "Status", "Date"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 7):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(360)
        self.table.cellDoubleClicked.connect(self._open)
        self.content.addWidget(self.table)
        self.content.addWidget(label("Double-click a row to show the file in Explorer.", "faint"))
        self.bridge.transfer_changed.connect(self._maybe_refresh)
        self.refresh()

    def _maybe_refresh(self, tid) -> None:
        t = self.node.repo.transfer(tid)
        if self.isVisible() and t and t.status not in ("active",):
            self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def _clear(self) -> None:
        if confirm(self.win, "Clear history?", "Completed, cancelled, declined and failed transfer records are "
                   "removed. Received files stay on disk.", "Clear"):
            for t in self.node.repo.transfers(("completed", "cancelled", "rejected", "failed")):
                self.node.repo.delete_transfer(t.id)
            self.refresh()

    def _open(self, row: int, _col: int) -> None:
        tid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        t = self.node.repo.transfer(tid)
        if not t:
            return
        if t.direction == "in":
            p = next((f.get("dest_path") for f in t.files if f.get("dest_path")), None)
            if p:
                system.reveal_file(p)
        else:
            system.reveal_file(t.files[0]["src_path"])

    def refresh(self) -> None:
        repo, p = self.node.repo, theme.palette()
        st = repo.transfer_stats(14)
        self.s_in.set(str(st["files_in"]), human_size(st["bytes_in"]))
        self.s_out.set(str(st["files_out"]), human_size(st["bytes_out"]))
        all_t = repo.transfers(limit=5000)
        finished = [t for t in all_t if t.status in ("completed", "failed")]
        ok = sum(1 for t in finished if t.status == "completed")
        self.s_ok.set(f"{(ok / len(finished) * 100) if finished else 100:.0f}%", f"{len(finished)} finished transfers")
        self.chart.set_data([time.strftime("%d", time.localtime(d + 43200)) for d in st["day_starts"]],
                            st["per_day_in"], st["per_day_out"])
        f = self.FILTERS[self.tabs.currentIndex()]
        q = self.search.text().strip().lower()
        names = {c.id: c.name for c in repo.contacts()}
        rows = []
        for t in all_t:
            if f == "Received" and t.direction != "in":
                continue
            if f == "Sent" and t.direction != "out":
                continue
            if f == "Failed" and t.status not in ("failed", "interrupted", "cancelled"):
                continue
            if q and q not in t.label.lower() and q not in names.get(t.contact_id, "").lower():
                continue
            rows.append(t)
        self.table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            name = QTableWidgetItem(icons.plain(system.file_icon_name(t.label), 16, p.cyan), t.label)
            name.setData(Qt.ItemDataRole.UserRole, t.id)
            status_txt = STATUS_TEXT.get(t.status, (t.status, ""))[0].split(" - ")[0]
            if t.status == "completed":
                status_txt = "Verified"
            vals = [names.get(t.contact_id, "Unknown"), "Received" if t.direction == "in" else "Sent",
                    human_size(t.total_bytes), self.node.transport_label(t.transport) if t.transport else "-",
                    status_txt, time.strftime("%d %b %Y %H:%M", time.localtime(t.created_at))]
            self.table.setItem(r, 0, name)
            for c, v in enumerate(vals, start=1):
                it = QTableWidgetItem(v)
                if c == 5:
                    color = {"completed": p.success, "failed": p.danger, "interrupted": p.warning}.get(t.status)
                    if color:
                        from PySide6.QtGui import QColor
                        it.setForeground(QColor(color))
                if t.error and c == 5:
                    it.setToolTip(t.error)
                self.table.setItem(r, c, it)
            self.table.setRowHeight(r, 40)
