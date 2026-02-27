# paperpilot.spec
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

block_cipher = None

a = Analysis(
    ['paperpilot/app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('paperpilot/assets', 'paperpilot/assets'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtWidgets',
        'PySide6.QtGui',
        'pydantic',
        'httpx',
        'rapidfuzz',
        'openpyxl',
    ],
    hookspath=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PaperPilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
