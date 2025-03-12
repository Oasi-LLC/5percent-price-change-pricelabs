# Code Snapshot System

Takes snapshots of your code and keeps them updated automatically. Perfect for documentation and code reviews.

## What it does
- Creates a single file containing all your project's code
- Updates automatically when you make changes
- Skips unnecessary files (like `venv` and `__pycache__`)
- Shows colorful status messages in terminal

## Quick Start

1. Install:
```bash
pip install -r requirements.txt
```

2. Use it:
```bash
# For a one-time snapshot:
python create_code_snapshot.py

# To watch for changes:
python auto-snapshot.py
```

## Configuration

Edit these in the scripts:
- File types to include (`WATCHED_EXTENSIONS`)
- Directories to skip (`EXCLUDE_DIRS`)
- Output file location (`SNAPSHOT_FILE`)

The snapshot will be saved as `full_code_snapshot.txt` in your project folder. 