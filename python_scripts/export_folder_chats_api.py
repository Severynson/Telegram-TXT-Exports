#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.utils import get_peer_id

from telegram_paths import DEFAULT_CONFIG_PATH, PROJECT_ROOT, load_dotenv_file, read_simple_yaml

DATE_RE = re.compile(
    r"\b([0-3]?\d\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    flags=re.IGNORECASE,
)


def _expand_env_scalar(value: object) -> str:
    expanded = os.path.expandvars(str(value or "")).strip()
    if re.search(r"\$(\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)", expanded):
        return ""
    return expanded


@dataclass(frozen=True)
class ApiConfig:
    api_id: int
    api_hash: str
    phone_number: str
    folder_title: str
    raw_dir: Path
    compiled_dir: Path
    session_dir: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export text-only message history from all chats in a Telegram folder "
            "using Telegram API (MTProto)."
        )
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--limit", type=int, default=0, help="Optional per-chat message cap (0 = unlimited).")
    return parser.parse_args()


def _expand_path(value: object, base_dir: Path) -> Path:
    text = str(value).strip()
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def load_api_config(path: Path) -> ApiConfig:
    load_dotenv_file()
    raw = read_simple_yaml(path)
    base_dir = path.parent

    api_id_text = _expand_env_scalar(raw.get("telegram_api_id") or "0")
    api_hash = _expand_env_scalar(raw.get("telegram_api_hash"))
    phone_number = _expand_env_scalar(raw.get("telegram_phone_number"))
    folder_title = _expand_env_scalar(raw.get("telegram_folder_title"))
    api_id = int(api_id_text or 0)

    if api_id <= 0:
        raise ValueError("configs.yaml: telegram_api_id must be a positive integer.")
    if not api_hash:
        raise ValueError("configs.yaml: telegram_api_hash is required.")
    if not phone_number:
        raise ValueError("configs.yaml: telegram_phone_number is required (E.164, e.g. +15551234567).")
    if not folder_title:
        raise ValueError("configs.yaml: telegram_folder_title is required.")

    raw_dir = _expand_path(raw.get("raw_dir") or "./data/raw", base_dir)
    compiled_dir = _expand_path(raw.get("output_dir") or "./data/compiled", base_dir)
    session_dir = _expand_path(raw.get("telegram_session_dir") or "./data/.telegram_session", base_dir)

    return ApiConfig(
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone_number,
        folder_title=folder_title,
        raw_dir=raw_dir,
        compiled_dir=compiled_dir,
        session_dir=session_dir,
    )


def parse_last_compiled_date(compiled_file: Path) -> datetime | None:
    if not compiled_file.exists():
        return None
    text = compiled_file.read_text(encoding="utf-8", errors="ignore")
    matches = DATE_RE.findall(text)
    if not matches:
        return None
    last = matches[-1]
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(last, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def sanitize_filename(title: str) -> str:
    title = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()
    title = re.sub(r"\s+", " ", title).rstrip(". ")
    return title[:180] if title else "chat"


def _folder_title_text(folder: object) -> str:
    title = getattr(folder, "title", "")
    if hasattr(title, "text"):
        text = getattr(title, "text", "")
        return str(text or "")
    return str(title or "")


def _normalize_folder_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", normalized)
    return normalized.strip().casefold()


def find_folder_by_title(filters: Iterable[object], title: str) -> object:
    target = _normalize_folder_title(title)
    available_titles: list[str] = []

    for f in filters:
        current_title = _folder_title_text(f)
        if current_title:
            available_titles.append(current_title)
        if _normalize_folder_title(current_title) == target:
            return f

    options = ", ".join(repr(t) for t in available_titles) if available_titles else "<none>"
    raise ValueError(
        f"Telegram folder not found by title: {title!r}. "
        f"Available folder titles: {options}"
    )


def collect_peer_ids(folder: object) -> set[int]:
    peer_ids: set[int] = set()
    for peer in getattr(folder, "include_peers", []) or []:
        try:
            peer_ids.add(int(get_peer_id(peer)))
        except Exception:
            continue
    for peer in getattr(folder, "pinned_peers", []) or []:
        try:
            peer_ids.add(int(get_peer_id(peer)))
        except Exception:
            continue
    return peer_ids


def collect_excluded_peer_ids(folder: object) -> set[int]:
    peer_ids: set[int] = set()
    for peer in getattr(folder, "exclude_peers", []) or []:
        try:
            peer_ids.add(int(get_peer_id(peer)))
        except Exception:
            continue
    return peer_ids


def _dialog_peer_id(dialog: object) -> int | None:
    try:
        return int(get_peer_id(dialog.entity))
    except Exception:
        return None


def _dialog_matches_folder_flags(dialog: object, folder: object) -> bool:
    # "include_peers" are always included; this function handles dynamic flags.
    contacts = bool(getattr(folder, "contacts", False))
    non_contacts = bool(getattr(folder, "non_contacts", False))
    groups = bool(getattr(folder, "groups", False))
    broadcasts = bool(getattr(folder, "broadcasts", False))
    bots = bool(getattr(folder, "bots", False))

    matches_dynamic = False
    if groups and bool(getattr(dialog, "is_group", False)):
        matches_dynamic = True
    if broadcasts and bool(getattr(dialog, "is_channel", False)):
        matches_dynamic = True
    if bots and bool(getattr(dialog.entity, "bot", False)):
        matches_dynamic = True

    is_user = bool(getattr(dialog, "is_user", False))
    is_contact = bool(getattr(dialog.entity, "contact", False))
    if contacts and is_user and is_contact:
        matches_dynamic = True
    if non_contacts and is_user and not is_contact:
        matches_dynamic = True

    return matches_dynamic


def dialog_in_folder(dialog: object, folder: object, included_ids: set[int], excluded_ids: set[int]) -> bool:
    peer_id = _dialog_peer_id(dialog)
    if peer_id is None:
        return False
    if peer_id in excluded_ids:
        return False

    if peer_id in included_ids:
        return True

    if not _dialog_matches_folder_flags(dialog, folder):
        return False

    if bool(getattr(folder, "exclude_muted", False)) and bool(getattr(dialog, "is_muted", False)):
        return False
    if bool(getattr(folder, "exclude_read", False)) and bool(getattr(dialog, "unread_count", 0) == 0):
        return False
    if bool(getattr(folder, "exclude_archived", False)) and bool(getattr(dialog, "archived", False)):
        return False
    return True


async def ensure_login(client: TelegramClient, phone_number: str) -> None:
    if await client.is_user_authorized():
        return
    sent = await client.send_code_request(phone_number)
    code = input("Enter Telegram login code: ").strip()
    try:
        await client.sign_in(phone=phone_number, code=code, phone_code_hash=sent.phone_code_hash)
    except SessionPasswordNeededError:
        pw = input("Two-step password: ").strip()
        await client.sign_in(password=pw)


async def export_folder(config: ApiConfig, per_chat_limit: int = 0) -> int:
    config.raw_dir.mkdir(parents=True, exist_ok=True)
    config.session_dir.mkdir(parents=True, exist_ok=True)
    session_file = config.session_dir / "telegram_api"

    client = TelegramClient(str(session_file), config.api_id, config.api_hash)
    await client.connect()
    try:
        await ensure_login(client, config.phone_number)

        filters = await client(GetDialogFiltersRequest())
        folder = find_folder_by_title(filters.filters, config.folder_title)
        included_peer_ids = collect_peer_ids(folder)
        excluded_peer_ids = collect_excluded_peer_ids(folder)

        exported_chats = 0
        async for dialog in client.iter_dialogs():
            if not dialog_in_folder(dialog, folder, included_peer_ids, excluded_peer_ids):
                continue

            title = dialog.name or str(dialog.id)
            compiled_file = config.compiled_dir / f"{title}.txt"
            last_dt = parse_last_compiled_date(compiled_file)

            output_name = sanitize_filename(title)
            out_file = config.raw_dir / f"{output_name}.txt"

            lines: list[str] = []
            async for msg in client.iter_messages(dialog.entity, reverse=True):
                if per_chat_limit > 0 and len(lines) >= per_chat_limit:
                    break
                if not msg.message:
                    continue
                msg_dt = msg.date.astimezone(timezone.utc)
                if last_dt and msg_dt <= last_dt:
                    continue
                author = "Unknown"
                if msg.sender_id:
                    author = str(msg.sender_id)
                stamp = msg_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                text = msg.message.replace("\r\n", "\n").replace("\r", "\n")
                lines.append(f"[{stamp}] {author}: {text}")

            if lines:
                mode = "a" if out_file.exists() else "w"
                with out_file.open(mode, encoding="utf-8") as fh:
                    if mode == "a":
                        fh.write("\n")
                    fh.write("\n".join(lines))
                    fh.write("\n")
                print(f"Wrote {len(lines)} text message(s): {out_file}")
                exported_chats += 1
            else:
                print(f"No new text messages: {title}")

        print(f"Done. Updated {exported_chats} chat file(s).")
        return 0
    finally:
        await client.disconnect()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    cfg = load_api_config(config_path)
    print("Step API: export folder chats to raw text")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Folder title: {cfg.folder_title}")
    return __import__("asyncio").run(export_folder(cfg, per_chat_limit=max(0, args.limit)))


if __name__ == "__main__":
    raise SystemExit(main())
