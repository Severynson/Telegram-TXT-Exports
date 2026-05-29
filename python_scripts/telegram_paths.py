from __future__ import annotations

import fnmatch
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# Source layout: <repo>/python_scripts/*.py
# Frozen layout (PyInstaller): executable is launched from app/<os>/ and should
# use the current working directory to find configs/data/temp.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path.cwd()
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs.yaml"
DEFAULT_TEMP_DIR = PROJECT_ROOT / "temp"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "compiled"


@dataclass(frozen=True)
class Config:
    telegram_download_folder: Path | None
    telegram_download_folders: tuple[Path, ...]
    include_autodetected_roots: bool
    transfer_mode: str
    temp_dir: Path
    output_dir: Path
    recursive_search: bool
    max_search_depth: int
    delete_temp_before_run: bool


def parse_scalar(value: str) -> object:
    value = value.strip()
    if not value or value.lower() in {"null", "none", "~"}:
        return None
    if value.lower() in {"true", "yes", "on"}:
        return True
    if value.lower() in {"false", "no", "off"}:
        return False
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def read_simple_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    result: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list_key:
            items = result.setdefault(current_list_key, [])
            if isinstance(items, list):
                items.append(parse_scalar(stripped[2:]))
            continue
        current_list_key = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            result[key] = []
            current_list_key = key
        else:
            result[key] = parse_scalar(value)
    return result


def expand_path(value: object, base_dir: Path | None = None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    raw = read_simple_yaml(config_path)
    base_dir = config_path.parent
    explicit_folder = expand_path(raw.get("telegram_download_folder"), base_dir)

    folders: list[Path] = []
    folder_values = raw.get("telegram_download_folders", [])
    if isinstance(folder_values, list):
        for item in folder_values:
            expanded = expand_path(item, base_dir)
            if expanded:
                folders.append(expanded)
    elif folder_values:
        expanded = expand_path(folder_values, base_dir)
        if expanded:
            folders.append(expanded)

    transfer_mode = str(raw.get("transfer_mode", "copy")).strip().lower()
    if transfer_mode not in {"copy", "move"}:
        raise ValueError("transfer_mode must be either 'copy' or 'move'.")

    return Config(
        telegram_download_folder=explicit_folder,
        telegram_download_folders=tuple(folders),
        include_autodetected_roots=bool(raw.get("include_autodetected_roots", True)),
        transfer_mode=transfer_mode,
        temp_dir=expand_path(raw.get("temp_dir"), base_dir) or DEFAULT_TEMP_DIR,
        output_dir=expand_path(raw.get("output_dir"), base_dir) or DEFAULT_OUTPUT_DIR,
        recursive_search=bool(raw.get("recursive_search", True)),
        max_search_depth=int(raw.get("max_search_depth", 4)),
        delete_temp_before_run=bool(raw.get("delete_temp_before_run", False)),
    )


def unique_existing_dirs(paths: Iterable[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_dir():
            result.append(resolved)
    return result


def platform_candidate_roots(home: Path) -> list[Path]:
    downloads = home / "Downloads"
    candidates = [
        downloads / "Telegram",
        downloads / "Telegram Desktop",
        downloads,
        downloads / "Telegram Downloads",
    ]
    if sys.platform == "darwin":
        candidates.extend(
            [
                home
                / "Library"
                / "Containers"
                / "ru.keepcoder.Telegram"
                / "Data"
                / "Downloads",
                home
                / "Library"
                / "Containers"
                / "org.telegram.desktop"
                / "Data"
                / "Downloads",
            ]
        )
    elif sys.platform.startswith("linux"):
        candidates.extend(
            [
                home / "snap" / "telegram-desktop" / "common" / "Downloads",
                home
                / ".var"
                / "app"
                / "org.telegram.desktop"
                / "data"
                / "TelegramDesktop",
                home / ".local" / "share" / "TelegramDesktop",
            ]
        )
    elif sys.platform.startswith("win"):
        for env_name in ("LOCALAPPDATA", "APPDATA"):
            env_path = os.environ.get(env_name)
            if env_path:
                candidates.append(Path(env_path) / "Telegram Desktop")
    return unique_existing_dirs(candidates)


def configured_roots(config: Config) -> list[Path]:
    roots: list[Path] = []
    if config.telegram_download_folder:
        roots.append(config.telegram_download_folder)
    roots.extend(config.telegram_download_folders)
    if config.include_autodetected_roots:
        roots.extend(platform_candidate_roots(Path.home()))
    return unique_existing_dirs(roots)


def within_depth(path: Path, root: Path, max_depth: int) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return len(rel.parts) <= max_depth


def find_chat_export_folders(
    roots: Sequence[Path], recursive: bool, max_depth: int
) -> list[Path]:
    found: dict[Path, None] = {}
    for root in roots:
        if fnmatch.fnmatch(root.name, "ChatExport_*"):
            found[root.resolve()] = None
            continue
        if not recursive:
            for child in root.iterdir():
                if child.is_dir() and fnmatch.fnmatch(child.name, "ChatExport_*"):
                    found[child.resolve()] = None
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            current = Path(dirpath)
            if not within_depth(current, root, max_depth):
                dirnames[:] = []
                continue
            if fnmatch.fnmatch(current.name, "ChatExport_*"):
                found[current.resolve()] = None
                dirnames[:] = []
    return sorted(found.keys(), key=lambda p: str(p).lower())
