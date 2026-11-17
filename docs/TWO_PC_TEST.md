# Two-PC acceptance test

You need **two Windows 10 (1803+) or 11 PCs** with Bluetooth. If you want to test the fast link too, they should be able to share a network: Wi-Fi, Ethernet, or one PC running *Mobile hotspot*.

You can do sections A-F with the two PCs alone; section G also needs a phone or tablet.

Record the result of each step (pass / fail / notes). Logs are in `%APPDATA%\Blue Cench Chat\logs\bluecenchchat.log`.

## A. Install

1. Run `BlueCenchChat-Setup.exe` on both PCs. Check that the Start-menu shortcut, the desktop shortcut and the uninstaller entry under *Apps* all exist.
2. Start Blue Cench Chat on both. If Windows Firewall asks, choose **Private networks → Allow**.
3. Create an account on each PC: **PC-A "alice"** and **PC-B "bob"**. Save the recovery keys.

## B. Compatibility

4. On both PCs, open *Bluetooth Devices → Run compatibility test*. Note which checks fail. If "Be discoverable (BLE advertising)" fails on a PC, other people can't find that PC over BLE. It can still be found over the local network or a paired RFCOMM link.

## C. Discovery and connection over Bluetooth only (no shared network)

5. Disconnect both PCs from all networks.
6. Pair the PCs once in *Settings → Bluetooth & devices → Add device* and confirm the PIN on both.
7. On PC-A, open *Discover People*. PC-B should appear, either as a BLE beacon showing signal bars or as "Paired with Windows". Press **Connect**.
8. On PC-B, a notification and a request in *My Connections → Requests* should appear. Press **Accept**.
9. On both PCs, the chat header should show the **Bluetooth RFCOMM** transport.
10. Compare the safety number on both PCs (*Verify*). The numbers must be identical. Mark the contact as verified.
11. Send messages both ways. Check the receipts go from clock to one tick to two ticks to cyan (read), and check typing, reply, reaction and delete for everyone.
12. Send a 5 MB file and check the speed shown (expect about 0.05–0.25 MB/s). The received file must say "SHA-256 verified".

## D. Fast link (no internet)

13. Turn on *Mobile hotspot* on PC-A and connect PC-B to it. Leave the other networks off.
14. Disconnect in Blue Cench Chat, then connect again from *Discover People*. The transport must now say **Local Network**.
15. Send a folder with sub-folders and one file larger than 1 GB. Check the speed and ETA.
16. In the middle of the large transfer, turn Wi-Fi off on PC-B for about 20 seconds. The transfer should show **Interrupted**. Turn Wi-Fi on again. The PCs should reconnect automatically within about a minute and continue from where they stopped, without restarting at 0%.
17. Pause and resume from the receiver, then cancel a transfer from the sender. Check that no `.part` files are left in `Downloads\Blue Cench Chat\.bluecenchchat-partial`.
18. Send the same file again. It should be skipped as a duplicate.

## E. Security

19. Block PC-A on PC-B. PC-A's connect attempts should be refused, and the event should appear in PC-B's security log.
20. Send an `.exe`. The receiver should get a warning before accepting, and running the received file should trigger Windows SmartScreen because of the Mark of the Web.
21. Enter a wrong password 5 times. The account should lock for 5 minutes.
22. Use *Forgot password* with the recovery key. You should be able to sign in again with the same Blue Cench Chat ID and contacts.

## F. Desktop integration

23. Close the window. Blue Cench Chat should stay in the tray, and a message from the other PC should raise a Windows notification.
24. Turn on *Settings → Start with Windows* and reboot. Blue Cench Chat should start minimized.
25. Create a backup, change something, restore the backup and restart Blue Cench Chat. The data should match the backup.

## Testing without Bluetooth hardware

Run `run-dev.bat alice` and `run-dev.bat bob` on one PC. This is the development test mode: two isolated profiles that talk over real localhost sockets. You can use *Connect with code* or the LAN discovery list.

## G. Phones, tablets and watches

26. On PC-A, open *Phones & Tablets* and switch on *Allow phones and tablets*. Put a phone on the same Wi-Fi (or on PC-A's Mobile hotspot).
27. Scan the QR code with the phone camera. Accept the certificate warning. The fingerprint should match the one on the PC. The phone should open Blue Cench Chat already paired.
28. On the phone, open the chat with PC-B's user and send a message, a quick reply and a photo (paperclip). Check that all three arrive on PC-B.
29. Send a file from PC-B to PC-A. Accept it on the phone (*Files*), then download it to the phone with *Save*.
30. Add the page to the home screen and check that it opens full-screen with the Blue Cench Chat icon.
31. Optional: open the same address on an iPad and on a smartwatch browser. The tablet should show the list and chat side by side. The watch should show compact tabs and quick replies.
32. On the PC, remove the phone under *Paired devices*. The phone should drop back to the pairing screen.
