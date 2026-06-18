"""
Aegis Setup Script
Usage:
    python setup.py              # Install dependencies
    python setup.py build        # Build standalone executable
    python setup.py build --dev  # Build dev version (with console)
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def install_deps():
    print("Installing requirements...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
    print("Installing Playwright browsers...")
    subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)
    print("\n✓ Setup complete! Run 'python main.py' to start Aegis.")
    print("  To build an executable: python build.py")


def build_app(dev_mode=False):
    print("Installing build dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    cmd = [sys.executable, "build.py"]
    if dev_mode:
        cmd.append("--dev")
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(BASE_DIR))
    print("\n✓ Build complete! Check the 'dist' folder.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        dev_mode = "--dev" in sys.argv
        build_app(dev_mode=dev_mode)
    else:
        install_deps()
