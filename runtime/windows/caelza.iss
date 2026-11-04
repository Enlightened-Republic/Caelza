; Caelza for Windows: per-user installer (no admin). Built in CI by release.yml:
;   ISCC /DAppVersion=0.1.1 /DSourceDir=<staged folder> /DOutDir=<out> caelza.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "stage"
#endif
#ifndef OutDir
  #define OutDir "out"
#endif

[Setup]
AppId={{8D1B6F52-5A4E-4C1B-9E27-CAE10A000001}
AppName=Caelza
AppVersion={#AppVersion}
AppPublisher=Enlightened Republic
AppPublisherURL=https://github.com/Enlightened-Republic/Caelza
DefaultDirName={localappdata}\Caelza
DefaultGroupName=Caelza
PrivilegesRequired=lowest
ChangesEnvironment=yes
OutputDir={#OutDir}
OutputBaseFilename=Caelza-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Caelza
DisableProgramGroupPage=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "caelza-launch.cmd"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Caelza"; Filename: "{app}\caelza-launch.cmd"; WorkingDir: "{app}"; Comment: "Start Caelza and open the dashboard"
Name: "{userdesktop}\Caelza"; Filename: "{app}\caelza-launch.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Add a Caelza shortcut to the desktop"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\caelza-launch.cmd"; Description: "Start Caelza now"; Flags: postinstall nowait skipifsilent shellexec

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Lowercase(Param) + ';', ';' + Lowercase(OrigPath) + ';') = 0;
end;
