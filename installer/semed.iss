; ============================================================
;  SEMED Energia — Script do instalador (Inno Setup 6)
; ============================================================
;  Compile com o Inno Setup Compiler (Compile / F9).
;  Pré-requisito: já ter rodado  pyinstaller semed.spec --noconfirm
;  para gerar a pasta  dist\SEMED Energia\.
;
;  Se for atualizar o token de auto-update, copie update_token.txt
;  para dentro de  dist\SEMED Energia\  ANTES de compilar.
; ============================================================

#define AppName "SEMED Energia"
#define AppPublisher "Prefeitura de Ananindeua - SEMED"
; A versão é lida da pasta de build; ajuste a cada release.
#define AppVersion "1.0.0"
#define AppExe "SEMED Energia.exe"

[Setup]
; AppId identifica o programa para upgrades. NÃO mude depois de publicado.
AppId={{B7E2F1A4-2C3D-4E5F-9A8B-1C2D3E4F5A6B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=SEMED-Energia-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Instala em Program Files -> requer elevação (padrão).
PrivilegesRequired=admin
SetupIconFile=..\ui\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
; Empacota TODA a pasta gerada pelo PyInstaller.
Source: "..\dist\SEMED Energia\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName} agora"; Flags: nowait postinstall skipifsilent
