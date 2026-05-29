#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import shutil
import subprocess
import sys
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from telegram_paths import DEFAULT_CONFIG_PATH, find_chat_export_folders, configured_roots, load_config


def unique_destination(src: Path, dst_dir: Path) -> Path:
    candidate = dst_dir / src.name
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    counter = 1
    while True:
        candidate = dst_dir / f"{src.name}_{stamp}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def trash_macos(path: Path) -> None:
    # Finder automation is noisy/unreliable in frozen binaries on some systems.
    # Move directly to ~/.Trash for deterministic behavior.
    trash_dir = Path.home() / ".Trash"
    trash_dir.mkdir(exist_ok=True)
    shutil.move(str(path), str(unique_destination(path, trash_dir)))


def trash_linux(path: Path) -> None:
    gio = shutil.which("gio")
    if gio:
        subprocess.check_call([gio, "trash", str(path)])
        return
    trash_put = shutil.which("trash-put")
    if trash_put:
        subprocess.check_call([trash_put, str(path)])
        return
    trash_root = Path.home() / ".local" / "share" / "Trash"
    files_dir = trash_root / "files"
    info_dir = trash_root / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(path, files_dir)
    original = path.resolve()
    shutil.move(str(path), str(destination))
    deletion_date = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    (info_dir / f"{destination.name}.trashinfo").write_text(
        "[Trash Info]\n"
        f"Path={original.as_posix()}\n"
        f"DeletionDate={deletion_date}\n",
        encoding="utf-8",
    )


def trash_windows(path: Path) -> None:
    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x0040
    FOF_NOCONFIRMATION = 0x0010
    FOF_NOERRORUI = 0x0400
    FOF_SILENT = 0x0004

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.hwnd = None
    operation.wFunc = FO_DELETE
    operation.pFrom = str(path) + "\0\0"
    operation.pTo = None
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(f"Recycle Bin operation failed with code {result}")


def move_to_trash(path: Path) -> None:
    if sys.platform == "darwin":
        trash_macos(path)
    elif sys.platform.startswith("linux"):
        trash_linux(path)
    elif sys.platform.startswith("win"):
        trash_windows(path)
    else:
        raise RuntimeError(f"Unsupported OS: {sys.platform}")


def maybe_close_terminal() -> None:
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("TCT_AUTO_CLOSE_TERMINAL", "1").strip() not in {"1", "true", "yes", "on"}:
        return
    if sys.platform == "darwin":
        script = 'tell application "Terminal" to if (count of windows) > 0 then close front window'
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
        return
    if sys.platform.startswith("linux"):
        # Best-effort: ask parent terminal process to terminate after tool exits.
        ppid = os.getppid()
        parent_name = ""
        try:
            comm_path = Path("/proc") / str(ppid) / "comm"
            parent_name = comm_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except Exception:
            return
        known_terms = (
            "gnome-terminal",
            "konsole",
            "xfce4-terminal",
            "xterm",
            "lxterminal",
            "tilix",
            "alacritty",
            "kitty",
        )
        if any(term in parent_name for term in known_terms):
            try:
                os.kill(ppid, signal.SIGTERM)
            except Exception:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 1: move old Telegram ChatExport_* folders to Trash/Recycle Bin."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config).expanduser().resolve())
    roots = configured_roots(config)
    print("Step 1: clean old Telegram exports")
    print("Search roots:")
    for root in roots:
        print(f"  - {root}")
    folders = find_chat_export_folders(roots, config.recursive_search, config.max_search_depth)
    if not folders:
        print("No ChatExport_* folders found.")
        return 0
    for folder in folders:
        if args.dry_run:
            print(f"Would move to trash: {folder}")
        else:
            print(f"Moving to trash: {folder}")
            move_to_trash(folder)
    print("Done.")
    return 0


if __name__ == "__main__":
    code = main()
    maybe_close_terminal()
    raise SystemExit(code)
