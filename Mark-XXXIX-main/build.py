"""
Aegis Build Script
Packages the application into a standalone executable using PyInstaller.
Usage:
    python build.py              # Build with release settings
    python build.py --dev        # Build with debug settings (one window)
    python build.py --upx UPX_DIR # Build with UPX compression
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from version import __version__, __app_name__, __author__

EXE_NAME = f"{__app_name__}.exe"

BUILD_DIR   = BASE_DIR / "build"
DIST_DIR    = BASE_DIR / "dist"
SPEC_FILE   = BASE_DIR / f"{__app_name__}.spec"
ICON_FILE   = BASE_DIR / "icon.ico"
DATA_DIRS   = ["config", "core", "memory", "actions", "agent"]
DATA_FILES  = ["version.py", "arc_reactor.html"]


def check_dependencies():
    missing = []
    try:
        import PyInstaller
    except ImportError:
        missing.append("pyinstaller")
    for mod in ["requests"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print(f"Install: pip install {' '.join(missing)}")
        sys.exit(1)


def clean_build():
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            shutil.rmtree(d)
    spec = BASE_DIR / f"{__app_name__}.spec"
    if spec.exists():
        spec.unlink()


def find_icon():
    if ICON_FILE.exists():
        return str(ICON_FILE)
    return None


def build(dev_mode=False, upx_dir=None):
    check_dependencies()
    clean_build()

    print(f"Building {__app_name__} v{__version__}...")
    print(f"  Mode: {'DEVELOPMENT' if dev_mode else 'RELEASE'}")
    print(f"  Python: {sys.executable}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", __app_name__,
        "--noconfirm",
        "--clean",
    ]

    if not dev_mode:
        cmd.append("--windowed")
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")
        cmd.append("--console")

    icon = find_icon()
    if icon:
        cmd.extend(["--icon", icon])

    vi_path = create_version_info()
    cmd.extend(["--version-file", str(vi_path)])

    cmd.extend(["--add-data", f"version.py{os.pathsep}."])

    hidden = [
        "sounddevice",
        "google.genai",
        "PIL",
        "cv2",
        "numpy",
        "psutil",
        "comtypes",
        "pycaw",
        "win10toast",
        "pywinauto",
        "pptx",
        "playwright",
        "bs4",
        "duckduckgo_search",
    ]
    for h in hidden:
        cmd.extend(["--hidden-import", h])

    for d in DATA_DIRS:
        src = BASE_DIR / d
        if src.exists():
            cmd.extend(["--add-data", f"{src}{os.pathsep}{d}"])

    for f in DATA_FILES:
        src = BASE_DIR / f
        if src.exists():
            cmd.extend(["--add-data", f"{src}{os.pathsep}."])

    if upx_dir:
        cmd.extend(["--upx-dir", upx_dir])

    cmd.append(str(BASE_DIR / "main.py"))

    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("\nBuild failed!")
        sys.exit(result.returncode)

    print(f"\nBuild successful! Output: {DIST_DIR / EXE_NAME}")


def create_version_info():
    vparts = __version__.replace("-", ".").split(".")
    vparts = (vparts + ["0", "0", "0"])[:3]
    filevers = ", ".join(vparts) + ", 0"
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({filevers}),
    prodvers=({filevers}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [StringStruct('CompanyName', '{__author__}'),
          StringStruct('FileDescription', '{__app_name__} - Real-time Voice AI Assistant'),
          StringStruct('FileVersion', '{__version__}'),
          StringStruct('InternalName', '{__app_name__}'),
          StringStruct('LegalCopyright', '\\u00a9 {__author__}'),
          StringStruct('OriginalFilename', '{EXE_NAME}'),
          StringStruct('ProductName', '{__app_name__}'),
          StringStruct('ProductVersion', '{__version__}')])
      ]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
"""
    path = BASE_DIR / "version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


if __name__ == "__main__":
    dev_mode = "--dev" in sys.argv
    upx_dir = None
    if "--upx" in sys.argv:
        idx = sys.argv.index("--upx")
        if idx + 1 < len(sys.argv):
            upx_dir = sys.argv[idx + 1]

    create_version_info()
    build(dev_mode=dev_mode, upx_dir=upx_dir)
