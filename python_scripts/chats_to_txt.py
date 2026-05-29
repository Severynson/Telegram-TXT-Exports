#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import signal
import shutil
import subprocess
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from telegram_paths import DEFAULT_CONFIG_PATH, find_chat_export_folders, configured_roots, load_config


MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = re.sub(r"\s+", " ", data).strip()
        if cleaned:
            self.parts.append(cleaned)


def safe_output_name(title: str, fallback: str) -> str:
    title = html.unescape(title).strip() or fallback
    title = re.sub(r"[\\/:*?\"<>|]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip().rstrip(". ")
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if not title or title.upper() in reserved:
        title = fallback
    return title[:180]


def title_from_compiled_text(compiled_text: str, fallback: str) -> str:
    pattern = re.compile(
        rf"Exported Data\s+(.+?)\s+\d{{1,2}}\s+(?:{'|'.join(MONTH_NAMES)})\s+\d{{4}}\b",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(compiled_text)
    if match:
        return safe_output_name(re.sub(r"\s+", " ", match.group(1)).strip(), fallback)
    return safe_output_name(fallback, fallback)


def extract_html_text(path: Path) -> str:
    parser = TextExtractor()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parser.parts)


def numbered_destination(temp_dir: Path, export_folder: Path) -> Path:
    base = temp_dir / export_folder.name
    if not base.exists():
        return base
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    counter = 1
    while True:
        candidate = temp_dir / f"{export_folder.name}_{stamp}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def transfer_export(export_folder: Path, temp_dir: Path, mode: str) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        export_folder.relative_to(temp_dir)
        return export_folder
    except ValueError:
        pass
    destination = numbered_destination(temp_dir, export_folder)
    if mode == "move":
        shutil.move(str(export_folder), str(destination))
    else:
        shutil.copytree(export_folder, destination)
    return destination


def compile_export(export_folder: Path, output_dir: Path) -> Path | None:
    html_files = sorted(export_folder.rglob("*.html"), key=lambda p: str(p).lower())
    if not html_files:
        return None
    chunks: list[str] = []
    for html_file in html_files:
        rel_name = html_file.relative_to(export_folder)
        chunks.append(f"\n\n===== {rel_name} =====\n")
        chunks.append(extract_html_text(html_file))
    compiled_text = "\n".join(chunks).strip() + "\n"
    title = title_from_compiled_text(compiled_text, export_folder.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{title}.txt"
    if output_path.exists():
        output_path = output_dir / f"{title} - {safe_output_name(export_folder.name, 'chat_export')}.txt"
    output_path.write_text(compiled_text, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 2: compile Telegram ChatExport_* HTML folders into TXT files."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


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
            ctypes = __import__("ctypes")
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


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config).expanduser().resolve())
    roots = configured_roots(config)
    print("Step 2: compile Telegram chats to TXT")
    print("Search roots:")
    for root in roots:
        print(f"  - {root}")
    if config.delete_temp_before_run and config.temp_dir.exists() and not args.dry_run:
        shutil.rmtree(config.temp_dir)
    folders = find_chat_export_folders(roots, config.recursive_search, config.max_search_depth)
    if not folders:
        print("No ChatExport_* folders found.")
        return 1
    count = 0
    for folder in folders:
        if args.dry_run:
            print(f"Would compile: {folder}")
            continue
        local_export = transfer_export(folder, config.temp_dir, config.transfer_mode)
        output_path = compile_export(local_export, config.output_dir)
        if output_path:
            count += 1
            print(f"Wrote: {output_path}")
        else:
            print(f"Skipped no HTML files: {folder}")
    print(f"Done. Compiled {count} export(s).")
    return 0 if count or args.dry_run else 1


if __name__ == "__main__":
    code = main()
    maybe_close_terminal()
    raise SystemExit(code)
