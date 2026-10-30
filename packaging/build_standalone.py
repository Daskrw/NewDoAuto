"""
Build script to package NewDoAuto into self-contained Windows executables:
1. dist/newdoauto.exe (CLI runner supporting 'run', 'validate', and 'ui')
2. dist/NewDoAuto-Desktop.exe (Windowed PySide6 desktop GUI application)

Ensures that all dependencies (Python runtime, uiautomation, comtypes, supabase,
python-dotenv, and PySide6) are bundled so the user does not need Python installed.
"""

import os
import subprocess
import sys


COMMON_HIDDEN_IMPORTS = [
    "--hidden-import", "uiautomation",
    "--hidden-import", "comtypes",
    "--hidden-import", "supabase",
    "--hidden-import", "dotenv",
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
]

EXCLUDED_UNUSED_MODULES = [
    "--exclude-module", "pytest",
    "--exclude-module", "setuptools",
    "--exclude-module", "Pygments",
    "--exclude-module", "tkinter",
    "--exclude-module", "PySide6.QtNetwork",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtOpenGL",
    "--exclude-module", "PySide6.QtSvg",
]


def _run_pyinstaller(
    root_dir: str,
    src_dir: str,
    dist_dir: str,
    build_dir: str,
    entry_point: str,
    exe_name: str,
    windowed: bool = False,
) -> bool:
    print(f"Building {exe_name}.exe from {entry_point}...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name",
        exe_name,
        "--paths",
        src_dir,
        *COMMON_HIDDEN_IMPORTS,
        *EXCLUDED_UNUSED_MODULES,
        "--distpath",
        dist_dir,
        "--workpath",
        os.path.join(build_dir, exe_name),
    ]
    if windowed:
        cmd.append("--windowed")
    cmd.append(entry_point)

    print(f"Running PyInstaller: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=root_dir)
    if result.returncode != 0:
        print(f"PyInstaller build for {exe_name} failed with return code {result.returncode}")
        return False

    exe_path = os.path.join(dist_dir, f"{exe_name}.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"Successfully generated self-contained executable: {exe_path} ({size_mb:.2f} MB)")
        return True

    print(f"Executable not found at {exe_path}")
    return False


def build_executable() -> bool:
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_dir = os.path.join(root_dir, "src")
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")

    cli_entry = os.path.join(src_dir, "newdoauto", "cli.py")
    gui_entry = os.path.join(src_dir, "newdoauto", "ui", "app.py")

    ok_gui = _run_pyinstaller(
        root_dir=root_dir,
        src_dir=src_dir,
        dist_dir=dist_dir,
        build_dir=build_dir,
        entry_point=gui_entry,
        exe_name="NewDoAuto-Desktop",
        windowed=True,
    )
    ok_cli = _run_pyinstaller(
        root_dir=root_dir,
        src_dir=src_dir,
        dist_dir=dist_dir,
        build_dir=build_dir,
        entry_point=cli_entry,
        exe_name="newdoauto",
        windowed=False,
    )
    return ok_gui and ok_cli


if __name__ == "__main__":
    success = build_executable()
    sys.exit(0 if success else 1)
