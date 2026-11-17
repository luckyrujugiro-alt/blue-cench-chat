; Inno Setup 6 script. Build the app first (pyinstaller bluecenchchat.spec), then compile this file.
#define AppName "Blue Cench Chat"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif

[Setup]
AppId={{6E1B6C2F-5E0B-4C55-9B3B-2B7C0F4F9A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Blue Cench Chat
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=BlueCenchChat-Setup
SetupIconFile=..\assets\logo\bluecenchchat.ico
UninstallDisplayIcon={app}\BlueCenchChat.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17134

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\BlueCenchChat\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Blue Cench Chat"; Filename: "{app}\BlueCenchChat.exe"; AppUserModelID: "BlueCenchChat.Desktop"
Name: "{group}\Uninstall Blue Cench Chat"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Blue Cench Chat"; Filename: "{app}\BlueCenchChat.exe"; Tasks: desktopicon; AppUserModelID: "BlueCenchChat.Desktop"

[Run]
; Private-network firewall rule so two PCs on the same network can find each other.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Blue Cench Chat"" dir=in action=allow program=""{app}\BlueCenchChat.exe"" profile=private enable=yes"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\BlueCenchChat.exe"; Description: "Launch Blue Cench Chat"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Blue Cench Chat"""; Flags: runhidden; RunOnceId: "BlueCenchChatFirewall"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
