; Inno Setup script for the Lime installer. windows/build.sh passes Version and SourceDir.
#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6E3C1F0A-7B3D-4C1E-9A55-4C1D2B7E9F10}
AppName=Lime
AppVersion={#Version}
AppPublisher=ThatSwimmerGuy
AppPublisherURL=https://github.com/ThatSwimmerGuy/Lime
DefaultDirName={autopf}\Lime
DefaultGroupName=Lime
DisableProgramGroupPage=yes
; per-user by default, so no admin prompt
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Lime-{#Version}-setup
SetupIconFile=lime.ico
UninstallDisplayIcon={app}\Lime.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "Start Lime when I sign in, so messages arrive in the background"; GroupDescription: "Other:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; the AppUserModelID lets Lime's notifications show under its own name and icon
Name: "{userprograms}\Lime"; Filename: "{app}\Lime.exe"; AppUserModelID: "io.github.ThatSwimmerGuy.Lime"
Name: "{userdesktop}\Lime"; Filename: "{app}\Lime.exe"; Tasks: desktopicon
Name: "{userstartup}\Lime"; Filename: "{app}\Lime.exe"; Tasks: startup

[Run]
Filename: "{app}\Lime.exe"; Description: "{cm:LaunchProgram,Lime}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Lime.exe /F"; Flags: runhidden; RunOnceId: "StopLime"
