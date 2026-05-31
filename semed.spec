# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec do SEMED Energia (modo pasta / onedir).

Gerar com:
    pyinstaller semed.spec --noconfirm

Saída:
    dist/SEMED Energia/SEMED Energia.exe   (+ pasta _internal)
É essa pasta inteira que vira o instalador e o pacote de atualização.
"""
import os
import re
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

block_cipher = None

# --- Versão do .exe (fonte única: version.py) -------------------------
# Embute o recurso de versão do Windows no executável (Propriedades > Detalhes).
# O instalador (installer/semed.iss) lê essa mesma versão do .exe gerado.
_ver_txt = re.search(
    r'__version__\s*=\s*["\']([^"\']+)["\']',
    open(os.path.join(SPECPATH, "version.py"), encoding="utf-8").read(),
).group(1)
_nums = [int(p) for p in _ver_txt.split(".") if p.isdigit()][:4]
while len(_nums) < 4:
    _nums.append(0)
_filevers = tuple(_nums)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_filevers, prodvers=_filevers, mask=0x3F,
                      flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Prefeitura de Ananindeua - SEMED"),
            StringStruct("FileDescription", "SEMED Energia"),
            StringStruct("FileVersion", _ver_txt),
            StringStruct("InternalName", "SEMED Energia"),
            StringStruct("OriginalFilename", "SEMED Energia.exe"),
            StringStruct("ProductName", "SEMED Energia"),
            StringStruct("ProductVersion", _ver_txt),
            StringStruct("LegalCopyright", "Prefeitura de Ananindeua"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
    ],
)

datas = [
    ("ui/assets/icon.ico", "ui/assets"),
    ("ui/assets/icon.png", "ui/assets"),
]
# Dados de libs que carregam recursos em runtime.
datas += collect_data_files("pdfminer")

# Token de auto-update (opcional). Se existir 'update_token.txt' na raiz do
# projeto, é embutido automaticamente no pacote (vai para _internal/), de modo
# que NÃO é preciso copiá-lo para dist/ a cada build. Nunca é commitado
# (está no .gitignore). O CI não tem esse arquivo, então as releases públicas
# saem sem o token — o token do cliente vem do instalador e sobrevive aos updates.
_token_src = os.path.join(SPECPATH, "update_token.txt")
if os.path.exists(_token_src):
    datas += [(_token_src, ".")]
    print("[semed.spec] update_token.txt embutido no pacote.")
else:
    print("[semed.spec] update_token.txt nao encontrado na raiz — pacote sem token.")

hiddenimports = [
    "version",
    "config",
    "update_config",
    "updater",
    # Modulos da camada de banco — alguns sao importados de forma tardia
    # (ex.: `from db.views_sqlite import criar_views_sqlite` dentro de
    # init_db()), entao garantimos que entrem no pacote.
    "db.models",
    "db.connection",
    "db.repository",
    "db.views_sqlite",
    # Auto-update: importados de forma tardia dentro de updater.py.
    "requests",
    "packaging",
    "packaging.version",
]
hiddenimports += collect_submodules("pyqtgraph")

a = Analysis(
    ["ui/app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["psycopg2", "tkinter", "PyQt5", "PyQt6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SEMED Energia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # app de janela, sem console
    icon="ui/assets/icon.ico",
    version=version_info,          # recurso de versão (Propriedades do .exe)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SEMED Energia",          # nome da pasta em dist/
)
