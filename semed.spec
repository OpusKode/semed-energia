# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec do SEMED Energia (modo pasta / onedir).

Gerar com:
    pyinstaller semed.spec --noconfirm

Saída:
    dist/SEMED Energia/SEMED Energia.exe   (+ pasta _internal)
É essa pasta inteira que vira o instalador e o pacote de atualização.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [
    ("ui/assets/icon.ico", "ui/assets"),
    ("ui/assets/icon.png", "ui/assets"),
]
# Dados de libs que carregam recursos em runtime.
datas += collect_data_files("pdfminer")

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
