"""
Build script to package NewDoAuto automation engine into a self-contained Windows executable.
Ensures that all dependencies (Python runtime, uiautomation, comtypes) are bundled
so the user does not need to install Python manually.
"""

import os
import subprocess
import sys


def build_executable():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_dir = os.path.join(root_dir, "src")
    entry_point = os.path.join(src_dir, "newdoauto", "cli.py")
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")

    print(f"Building self-contained NewDoAuto Windows executable from {entry_point}...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "newdoauto",
        "--paths",
        src_dir,
        "--hidden-import",
        "uiautomation",
        "--hidden-import",
        "comtypes",
        "--distpath",
        dist_dir,
        "--workpath",
        build_dir,
        entry_point,
    ]

    print(f"Running PyInstaller: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root_dir)
    if result.returncode != 0:
        print(f"PyInstaller build failed with return code {result.returncode}")
        return False

    exe_path = os.path.join(dist_dir, "newdoauto.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"Successfully generated self-contained executable: {exe_path} ({size_mb:.2f} MB)")
        return True
    else:
        print(f"Executable not found at {exe_path}")
        return False


if __name__ == "__main__":
    success = build_executable()
    sys.exit(0 if success else 1)
