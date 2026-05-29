#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python_scripts"
BUILD_ROOT = ROOT / "build"
APP_ROOT = ROOT / "app"

TARGETS = {
    "darwin": ("macos", ""),
    "linux": ("linux", ""),
    "win32": ("windows", ".exe"),
}

SCRIPTS = {
    "clean_old_exports": SCRIPTS_DIR / "clean_old_exports.py",
    "chats_to_txt": SCRIPTS_DIR / "chats_to_txt.py",
    "export_folder_chats_api": SCRIPTS_DIR / "export_folder_chats_api.py",
}


def platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "win32"
    raise RuntimeError(f"Unsupported platform for executable build: {sys.platform}")


def ensure_build_dependencies() -> None:
    packages: list[str] = []
    if not shutil.which("pyinstaller"):
        packages.append("pyinstaller")
    try:
        __import__("telethon")
    except ImportError:
        packages.append("telethon")
    if packages:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])


def run_pyinstaller(script_name: str, script_path: Path, out_dir: Path) -> Path:
    work_root = BUILD_ROOT / script_name
    work_path = work_root / "work"
    spec_path = work_root / "spec"
    config_dir = work_root / "pyinstaller_config"
    for path in (work_path, spec_path, config_dir, out_dir):
        path.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--clean",
        "--name",
        script_name,
        "--workpath",
        str(work_path),
        "--specpath",
        str(spec_path),
        "--distpath",
        str(out_dir),
        str(script_path),
    ]
    env = os.environ.copy()
    env["PYINSTALLER_CONFIG_DIR"] = str(config_dir)
    subprocess.check_call(command, cwd=ROOT, env=env)

    if sys.platform.startswith("win"):
        return out_dir / f"{script_name}.exe"
    return out_dir / script_name


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build native executables for the current OS using PyInstaller. "
            "Run on each target OS to fill app/macos, app/linux, and app/windows."
        )
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove current OS app output and build temp data first.",
    )
    args = parser.parse_args()

    os_key = platform_key()
    folder_name, _extension = TARGETS[os_key]
    out_dir = APP_ROOT / folder_name

    if args.clean:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)

    ensure_build_dependencies()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building native executables for: {folder_name}")
    for script_name, script_path in SCRIPTS.items():
        built = run_pyinstaller(script_name, script_path, out_dir)
        print(f"Built: {built}")

    (APP_ROOT / "macos").mkdir(parents=True, exist_ok=True)
    (APP_ROOT / "linux").mkdir(parents=True, exist_ok=True)
    (APP_ROOT / "windows").mkdir(parents=True, exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
