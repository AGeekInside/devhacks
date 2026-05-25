"""remove_every_other_file.py - Remove every other file (even-indexed) from a directory.

Usage:
    python remove_every_other_file.py <directory>

Warning:
    Destructive operation — removes files permanently (no trash/undo).
"""
import os
import sys

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <directory>")
    sys.exit(1)

directory = sys.argv[1]
if not os.path.isdir(directory):
    print(f"Error: {directory} is not a valid directory.")
    sys.exit(1)

files = sorted([f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))])
for i, filename in enumerate(files):
    if i % 2 == 0:
        file_path = os.path.join(directory, filename)
        print(f"Removing: {file_path}")
        os.remove(file_path)
