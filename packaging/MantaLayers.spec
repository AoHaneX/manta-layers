# PyInstaller recipe of the Windows build: one folder, no console.
# Built by packaging/build.ps1; run directly with: pyinstaller packaging/MantaLayers.spec
import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
NUMBERS = tuple(int(part) for part in re.findall(r"\d+", VERSION)[:3]) + (0,) * 3

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=NUMBERS[:4], prodvers=NUMBERS[:4]),
    kids=[
        StringFileInfo([StringTable("040C04B0", [
            StringStruct("CompanyName", "Blue Shrimp"),
            StringStruct("FileDescription", "Manta Layers"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "MantaLayers"),
            StringStruct("LegalCopyright", "Code MIT ; illustrations tous droits réservés"),
            StringStruct("OriginalFilename", "MantaLayers.exe"),
            StringStruct("ProductName", "Manta Layers"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x040C, 1200])]),
    ],
)

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "exemples"), "exemples"),
        # Only the notice: fonts a developer drops into fonts/ may not be redistributable.
        (str(ROOT / "fonts" / "README.txt"), "fonts"),
    ],
    # The local AI is optional and not shipped; the application detects its absence.
    excludes=["numpy", "onnxruntime", "tkinter"],
    noarchive=False,
)
# Software OpenGL fallback (20 MB): the interface only uses raster widgets.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != "opengl32sw.dll"]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MantaLayers",
    icon=str(ROOT / "assets" / "manta.ico"),
    version=version_info,
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MantaLayers", upx=False)
