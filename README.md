# Telegram Chat Tools

This project is now organized for executable-first usage (no Python required on end-user machines).

## Project structure

- `python_scripts/`
- `python_scripts/clean_old_exports.py` (step 1 logic)
- `python_scripts/chats_to_txt.py` (step 2 logic)
- `python_scripts/export_folder_chats_api.py` (Telegram API text export by folder)
- `python_scripts/telegram_paths.py` (shared config/path logic)
- `python_scripts/build_executables.py` (PyInstaller build script)
- `app/macos/` (macOS executables after building on macOS)
- `app/linux/` (Linux executables after building on Linux)
- `app/windows/` (Windows executables after building on Windows)
- `configs.yaml` (runtime config used by scripts/executables)
- `data/compiled/` (TXT output)
- `data/raw/` (API raw text output)

## End-user workflow (no Python)

Users should run only native executables from `app/<os>/`:

- Step 1: `clean_old_exports` (`.exe` on Windows)
- Step 2: `chats_to_txt` (`.exe` on Windows)
- Step API: `export_folder_chats_api` (`.exe` on Windows)

These binaries can be shared with non-developers and do not require Python installed.

## Build executables (for maintainers)

PyInstaller cannot cross-compile, so build on each target OS separately.

Install dependency:

```bash
python3 -m pip install pyinstaller
```

Build for current OS:

```bash
python3 python_scripts/build_executables.py --clean
```

Build outputs:

- macOS: `app/macos/clean_old_exports`, `app/macos/chats_to_txt`, `app/macos/export_folder_chats_api`
- Linux: `app/linux/clean_old_exports`, `app/linux/chats_to_txt`, `app/linux/export_folder_chats_api`
- Windows: `app/windows/clean_old_exports.exe`, `app/windows/chats_to_txt.exe`, `app/windows/export_folder_chats_api.exe`

## Telegram API export flow

`export_folder_chats_api` exports text-only messages from all chats in one Telegram folder (`telegram_folder_title`) into `data/raw`.

Incremental behavior:

- For each chat title, it checks `data/compiled/<chat_title>.txt`.
- It scans for the last date like `28 May 2026`.
- If found, it exports only newer text messages from that date onward.
- If not found, it exports the full text history available through API.

Setup in `configs.yaml`:

- `telegram_api_id`
- `telegram_api_hash`
- `telegram_phone_number` (example: `+15551234567`)
- `telegram_folder_title` (exact Telegram folder name)

On `https://my.telegram.org` when creating API credentials (`API development tools` -> `Create new application`), use these same selections:

- `App title`: `Telegram chats exporter`
- `Short name`: `tgchatexport` (alphanumeric, 5-32 chars)
- `URL`: `http://localhost`
- `Platform`: select `Other (specify in description)`
- `Description`: `Local desktop tool to export my Telegram chat text history via Telegram API for personal backup/processing.`

Keep these values the same so your setup matches this project docs.

First run prompts for Telegram login code (and 2FA password if enabled), then stores session in `data/.telegram_session`.

## Developer source usage (optional)

If you want to run raw Python source directly:

```bash
python3 python_scripts/clean_old_exports.py
python3 python_scripts/chats_to_txt.py
python3 python_scripts/export_folder_chats_api.py
```
