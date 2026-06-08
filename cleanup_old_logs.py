# cleanup_old_logs.py
"""
Cleanup script for old/derived log files in polyou_4/logs.

This script will move old/partial/derived log files to the logs/archive/ folder for safekeeping.

Only the main logs (execution_log.csv, exit_log.csv, gate_blocks.csv, rr_blocks.csv, decision_log.csv) will remain in logs/.
"""
import os
import shutil

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")
ARCHIVE_DIR = os.path.join(LOGS_DIR, "archive")
DERIVED_DIR = os.path.join(LOGS_DIR, "derived")

# Files to archive from logs/
FILES_TO_ARCHIVE = [
    "bot.log",
    "bot_realtime.log",
    "clob_ticks.csv",
    "execution_log.archive.csv",
    "execution_log.combined.csv",
    "execution_log.v2_partial.csv",
    "percent_move_audit.csv",
]

# Folders to archive
FOLDERS_TO_ARCHIVE = [
    DERIVED_DIR,
]

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def move_file(src, dst_dir):
    ensure_dir(dst_dir)
    dst = os.path.join(dst_dir, os.path.basename(src))
    print(f"Moving {src} -> {dst}")
    shutil.move(src, dst)

def main():
    # Move files
    for fname in FILES_TO_ARCHIVE:
        src = os.path.join(LOGS_DIR, fname)
        if os.path.exists(src):
            move_file(src, ARCHIVE_DIR)
    # Move folders
    for folder in FOLDERS_TO_ARCHIVE:
        if os.path.exists(folder):
            dst = os.path.join(ARCHIVE_DIR, os.path.basename(folder))
            print(f"Moving folder {folder} -> {dst}")
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(folder, dst)
    print("Cleanup complete.")

if __name__ == "__main__":
    main()
