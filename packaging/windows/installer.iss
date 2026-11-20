; 心理健康助手 Windows 安装脚本(Inno Setup 6)。
; 由 packaging/windows/build.ps1 调用:ISCC.exe /DAppVersion=<版本> installer.iss
; 依赖:..\..\dist\mhagent-desktop\(PyInstaller one-folder 产物)
;       ..\..\build\windows\config.yaml(build.ps1 生成的运行配置)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "心理健康助手"
#define AppExeName "mhagent-desktop.exe"

[Setup]
AppId={{8B2F0C4E-6D1A-4C77-9F6B-2E9A1B7D3C55}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={localappdata}\Programs\mhagent
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\artifacts
OutputBaseFilename=mhagent-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\..\dist\mhagent-desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 仅在不存在时安装,避免覆盖用户修改过的网关地址等配置。
Source: "..\..\build\windows\config.yaml"; DestDir: "{app}"; DestName: "config.yaml"; Flags: onlyifdoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Parameters: "--config ""{app}\config.yaml"""
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Parameters: "--config ""{app}\config.yaml"""; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: "--config ""{app}\config.yaml"""; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

; 用户数据位于 %USERPROFILE%\.mhagent,卸载时保留;{app} 下由安装清单自动清理。
