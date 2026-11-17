# Blue Cench Chat — Connect Beyond Limits.

Blue Cench Chat is a Windows desktop app for finding people nearby, connecting with their consent, chatting privately and moving files of any size. It needs no internet connection: devices talk directly over **Bluetooth** or a **shared local network** (Wi-Fi, Ethernet or a Windows Mobile Hotspot).

Phones, iPads and smartwatches use Blue Cench Chat through a responsive web app that the PC serves over the same Wi-Fi or its Mobile Hotspot. There is nothing to install from an app store.

---

## 1. Feature status (honest)

| Area | Status |
|---|---|
| Accounts: register, sign in, Argon2id, lockout, offline recovery key, guest mode, change password | Implemented and covered by automated tests |
| Encrypted sessions: X25519 + Ed25519 signed handshake, HKDF, ChaCha20-Poly1305, anti-replay | Implemented and tested, including impersonation and tamper attempts |
| Connection requests, accept/reject, block, report, trusted/verified contacts, safety numbers | Implemented and tested |
| Chat: delivery/read receipts, typing, reply, reactions (icons), delete for me/everyone, search, offline queue | Implemented and tested |
| File engine: files, multi-file, folders, chunking, ACK flow control, pause/resume/cancel, SHA-256, resume after disconnect, duplicate skip, path-traversal protection | Implemented and tested over real TCP sockets |
| Local-network transport + presence discovery (UDP beacons) | Implemented and tested |
| Identity code / QR identity pairing (key pinning → auto-verified) | Implemented and tested |
| UI: 12 sidebar pages, dashboard charts, dark + light theme, text scaling, reduce motion, onboarding tour, tray | Implemented; every page is rendered in a headless test |
| Backup & restore | Implemented and tested |
| **Bluetooth LE discovery (advertise + scan), RFCOMM transport, adapter diagnostics, paired-device list** | Written against the Windows Runtime APIs. **It can only run on Windows with Bluetooth hardware, so it has not been run yet.** Use `docs/TWO_PC_TEST.md` to validate it. |
| Windows-only extras: DPAPI "keep me signed in", Start with Windows, Mark-of-the-Web on received files, toast notifications | Written for Windows. Not run yet for the same reason. |
| `BlueCenchChat.exe` + installer | Scripts included (`build.ps1`, `bluecenchchat.spec`, `installer/bluecenchchat.iss`). They must be run on Windows, because PyInstaller cannot cross-compile. |
| **Phones, tablets, watches:** responsive web app over Wi-Fi/hotspot. Pairing by QR or 6-digit code, HTTPS, chat, quick replies, file send from the phone, file download, connection requests, nearby list, live updates | Implemented and tested with a real HTTPS server and real browser renders at watch, phone and tablet sizes |
| Responsive desktop layout: icon-only navigation rail and tighter pages below 1180 px wide | Implemented |
| Not in v1 | Voice messages, multi-language UI, automatic updates (needs an update server), internet-assisted sync, group conversations (you can hold several 1:1 sessions at once). |

---

## 2. Phones, tablets and watches

On the PC, open **Phones & Tablets** and switch on *Allow phones and tablets*.

1. Put the phone on the same Wi-Fi as the PC. Or turn on **Mobile hotspot** on the PC and join it from the phone; this works with no internet.
2. Scan the QR code with the phone's camera, or open the address shown and type the 6-digit code. The code changes every 5 minutes and works only once.
3. The browser warns that the connection is "not private". That's because the PC made its own HTTPS certificate instead of buying one from an internet company. The traffic is still encrypted. You can compare the fingerprint shown on the PC, then choose *Advanced / Show details → Proceed*.
4. Add the page to the home screen (*Share → Add to Home Screen* on iPhone/iPad, *Install app* in Chrome on Android) so it opens like an app.

The layout adapts to the screen:
* **Watches:** compact list, icon-only tabs and one-tap quick replies.
* **Phones:** bottom tabs and full-screen chats.
* **Tablets and desktops:** a navigation rail with list and chat side by side.

**Why the phone doesn't use its own Bluetooth.** Phone browsers can't publish Bluetooth services or open RFCOMM links, and iPhone/iPad browsers have no Bluetooth at all. The PC therefore keeps the Bluetooth and local-network links and the encryption keys. Paired phones act as secure remote screens for the PC's Blue Cench Chat account. A paired device can be removed from the PC at any time and is signed out immediately.

## 3. What Bluetooth on Windows can and cannot do

* **Finding Blue Cench Chat users.** A plain Bluetooth scan can't tell which devices run Blue Cench Chat. Each running instance therefore publishes a **BLE advertisement**: company ID `0xFFFF` plus a 23-byte payload holding a magic byte, an 8-byte identity hint, flags, LAN IP/port and the Classic Bluetooth address. Other instances watch for it and read the RSSI as signal strength.
  * Publishing needs an adapter whose driver supports the **BLE peripheral role**, and many USB dongles don't. *Bluetooth Devices → Run compatibility test* tells you whether yours does.
  * `0xFFFF` is the Bluetooth SIG test ID. A commercial release must register its own company ID.
* **Identity is proven in the handshake, not by discovery.** A beacon only says "someone with hint X is here". The Blue Cench Chat ID is a hash of the Ed25519 key, and the peer must sign the session transcript with that key.
* **RFCOMM** (Bluetooth Classic) is the Bluetooth data link. Blue Cench Chat publishes an SDP record with its own service UUID. Windows normally requires the two PCs to be **paired once** in *Settings → Bluetooth & devices*. Blue Cench Chat never pairs or trusts anything silently.
* **Throughput.** RFCOMM is about **50–250 KB/s**, so 1 GB takes roughly 1–5 hours. Large files should use the **local-network transport** at about 5–100 MB/s. You can create that network with no internet by turning on *Mobile hotspot* on one PC and joining it from the other. Raw Wi-Fi Direct sockets are not reachable from Python on Windows; the hotspot is the practical equivalent.
* **Which transport is used** is always shown on chats, transfers and the Devices page.
* **Group mode.** RFCOMM is point-to-point. Blue Cench Chat runs several independent encrypted 1:1 sessions at the same time.

---

## 4. Architecture

```
main.py                      entry point: logging (redacted), single instance, qasync loop
bluecenchchat/
  config.py                  paths (%APPDATA%\Blue Cench Chat), protocol constants, dev profiles
  app.py                     controller: sign-in -> engine -> main window -> sign-out
  core/                      UI-independent engine (asyncio)
    crypto.py                identity, ID derivation, safety numbers, key wrap, AEAD channel
    session.py               framing + signed handshake + encrypted messages / chunks
    node.py                  BlueCenchChatNode: owns everything below, event bus
    connection_manager.py    sessions, requests, trust, blocking, keep-alive, auto-reconnect
    discovery_engine.py      merges BLE / LAN / paired-RFCOMM sightings
    messaging.py             chat, receipts, typing, reactions, offline queue
    transfer_engine.py       chunked resumable transfers, flow control, SHA-256, duplicates
    file_safety.py           filename sanitising, traversal protection, Mark-of-the-Web
    transports/
      base.py                Stream interface
      lan.py                 TCP transport + UDP presence beacons
      bluetooth.py           WinRT: adapter info, BLE beacon, RFCOMM server/client
  backend/
    database.py, models.py   SQLAlchemy 2 + SQLite (WAL)
    authentication.py        Pydantic validation, Argon2id, lockout, recovery
    user_service.py          account-scoped repository
    secure_store.py          DPAPI-protected "keep me signed in"
    backup.py                snapshot backup / staged restore
  web/                       Wi-Fi companion: FastAPI + uvicorn (HTTPS), pairing, REST + WebSocket API
    static/                  the responsive web app (no build step): index.html, app.css, app.js
  ui/                        PySide6 + QSS design system, Lucide SVG icons, 13 pages
tests/                       52 tests: auth, crypto, sessions, two real nodes, web companion, UI smoke
.github/workflows/           GitHub Actions: builds BlueCenchChat.exe + installer on Windows
installer/                   Inno Setup script + version resource
```

**Where FastAPI fits.** The desktop UI calls the engine directly through an event bus (`ui/bridge.py`). The FastAPI service runs only when you turn on phone access. It is HTTPS-only, and every route except pairing requires a paired device's session.

**Wire protocol.** Frames are `[u32 length][payload]`. The handshake runs HELLO → HELLO, then derives keys with X25519 + HKDF (salted with the transcript hash). Each side then sends an encrypted AUTH that holds its Ed25519 signature over the transcript. Every later frame is ChaCha20-Poly1305 with a per-direction counter nonce. File chunks are binary frames carrying `(transfer id, file index, offset)`. Control messages are JSON and rate-limited.

**Accounts offline vs online.** Accounts and keys exist only on the PC. The identity key is stored encrypted under the password, with a second copy encrypted under the recovery key. Without the recovery key a password can't be reset; that is deliberate, because there is no server. A future internet-assisted mode would add optional sync and keep the local key as the root of trust.

---

## 5. Run from source

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python main.py
```

**Development test mode** (clearly separate from production): run two isolated profiles on one PC. They talk over real localhost sockets, so nothing is simulated.

```powershell
run-dev.bat alice
run-dev.bat bob
```

Tests:

```powershell
.venv\Scripts\python -m pytest -q
```

## 6. Build BlueCenchChat.exe and the installer

**Easiest: let GitHub build it.** Push this folder to a GitHub repository. The workflow in `.github/workflows/build-windows.yml` runs on GitHub's Windows servers: it runs the tests, then builds `BlueCenchChat.exe` and `BlueCenchChat-Setup-1.0.0.exe`. Download them from the run's **Artifacts** in the repository's **Actions** tab.

**On your own Windows PC:**

1. Install Python 3.12 or newer (64-bit) and, for the installer, [Inno Setup 6](https://jrsoftware.org/isdl.php).
2. In PowerShell, from the project folder, run `.\build.ps1`.

The script creates a venv, runs the tests and builds `dist\BlueCenchChat\BlueCenchChat.exe`. If Inno Setup is installed, it also builds `dist\BlueCenchChat-Setup-1.0.0.exe`.

The installer provides:
* Start-menu and optional desktop shortcuts
* an uninstaller
* a private-network firewall rule (when installed for all users)
* a version resource and the app icon

User data stays in `%APPDATA%\Blue Cench Chat` after uninstalling, and logs are in `%APPDATA%\Blue Cench Chat\logs`.

## 7. Testing with two real Windows PCs

See **`docs/TWO_PC_TEST.md`** for the step-by-step checklist.

## 8. Licences

Icons: [Lucide](https://lucide.dev) (ISC), see `assets/icons/LICENSE-lucide.txt`. The libraries keep their own licences: PySide6 (LGPLv3), cryptography (Apache/BSD), argon2-cffi (MIT), SQLAlchemy (MIT), pydantic (MIT), qasync (BSD), qrcode (BSD), PyWinRT (MIT).
