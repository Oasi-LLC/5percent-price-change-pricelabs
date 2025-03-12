import os
import time
from pathlib import Path

# Directories to exclude from the snapshot
EXCLUDED_DIRS = {
    '.git',
    '__pycache__',
    'venv',
    'env',
    '.venv',
    '.env',
    'node_modules',
    '.pytest_cache',
    'data'  # Adding data directory to exclusions
}

def get_project_root():
    """Get the project root directory (where this script is run from)."""
    return os.getcwd()

def should_include_file(file_path):
    """Return True if we should include this file in the snapshot."""
    # Skip these files/directories
    excluded = {
        '.git', '__pycache__', '.env', '.venv', 'venv',
        '.DS_Store', '.idea', '.vscode', 'node_modules',
        '.csv', '.json', '.pyc', '.pyo', '.pyd', '.so',
        'full_code_snapshot.txt'
    }
    
    # Skip any path containing excluded terms
    path_parts = file_path.split(os.sep)
    return not any(ex in path_parts or file_path.endswith(ex) for ex in excluded)

def create_snapshot(project_root):
    """Create a snapshot of all code files in the project."""
    snapshot_path = os.path.join(project_root, "full_code_snapshot.txt")
    
    print(f"Working from project root: {project_root}")
    print(f"Scanning directory: {project_root}")
    
    with open(snapshot_path, "w", encoding="utf-8") as out:
        for root, dirs, files in os.walk(project_root):
            # Remove excluded directories
            dirs[:] = [d for d in dirs if should_include_file(d)]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, project_root)
                
                if should_include_file(rel_path):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            
                        out.write(f"\n{'='*80}\n")
                        out.write(f"File: {rel_path}\n")
                        out.write(f"{'='*80}\n\n")
                        out.write(content)
                        out.write("\n")
                        
                        print(f"Added file: {rel_path}")
                    except Exception as e:
                        print(f"Error reading {rel_path}: {e}")
    
    print(f"Code snapshot created at: {snapshot_path}")
    return str(snapshot_path)

if __name__ == "__main__":
    project_root = get_project_root()
    create_snapshot(project_root)