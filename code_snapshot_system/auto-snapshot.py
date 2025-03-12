import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
from termcolor import colored

# Use relative import
from create_code_snapshot import create_code_snapshot

# Define which file extensions we want to watch
WATCHED_EXTENSIONS = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".css", ".js", ".html"}
SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "full_code_snapshot.txt")

class CodeChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        # Ignore directory-level events and the snapshot file itself
        if event.is_directory or Path(event.src_path).name == Path(SNAPSHOT_FILE).name:
            return
        
        # Check if the modified file has an extension we care about
        file_extension = Path(event.src_path).suffix.lower()
        if file_extension in WATCHED_EXTENSIONS:
            print(colored(f"File changed: {event.src_path}. Updating code snapshot...", "yellow"))
            try:
                # Move up one directory to project root
                os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                create_code_snapshot(
                    directories=["."], 
                    output_file=SNAPSHOT_FILE
                )
                print(colored("✓ Snapshot updated successfully", "green"))
            except Exception as e:
                print(colored(f"✗ Error updating snapshot: {str(e)}", "red"))

if __name__ == "__main__":
    # Move up one directory to project root
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    watch_directory = "."  # Watch from project root
    event_handler = CodeChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, watch_directory, recursive=True)

    print(colored(f"Starting watch on '{os.path.abspath(watch_directory)}'...", "cyan"))
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(colored("\nStopping file watch...", "yellow"))
        observer.stop()
    observer.join()