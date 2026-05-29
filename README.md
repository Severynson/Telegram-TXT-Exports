# Telegram Chat Tools

This project is now organized for executable-first usage (no Python required on end-user machines).

## Project structure

- `python_scripts/`
- `python_scripts/clean_old_exports.py` (step 1 logic)
- `python_scripts/chats_to_txt.py` (step 2 logic)
- `python_scripts/telegram_paths.py` (shared config/path logic)
- `python_scripts/build_executables.py` (PyInstaller build script)
- `app/macos/` (macOS executables after building on macOS)
- `app/linux/` (Linux executables after building on Linux)
- `app/windows/` (Windows executables after building on Windows)
- `configs.yaml` (runtime config used by scripts/executables)
- `data/compiled/` (TXT output)

## End-user workflow (no Python)

Users should run only native executables from `app/<os>/`:

- Step 1: `clean_old_exports` (`.exe` on Windows)
- Step 2: `chats_to_txt` (`.exe` on Windows)

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

- macOS: `app/macos/clean_old_exports`, `app/macos/chats_to_txt`
- Linux: `app/linux/clean_old_exports`, `app/linux/chats_to_txt`
- Windows: `app/windows/clean_old_exports.exe`, `app/windows/chats_to_txt.exe`

## Developer source usage (optional)

If you want to run raw Python source directly:

```bash
python3 python_scripts/clean_old_exports.py
python3 python_scripts/chats_to_txt.py
```
