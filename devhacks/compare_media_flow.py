#!/usr/bin/env python3
# compare_media_flow.py
# Scan ingest dirs (/nfs/multimedia/data/{torrents,usenet}/completed) vs libraries.
# Reports counts, sizes, % organized, and a backlog list of unprocessed items.

import argparse, os, re, sys, json, hashlib, shutil, stat, io, contextlib
from collections import defaultdict, namedtuple
from datetime import datetime

Row = namedtuple("Row", "source files bytes matched unmatched pct_matched")

DEFAULT_INGEST = [
    "/nfs/multimedia/data/torrents/completed",
    "/nfs/multimedia/data/usenet/completed",
]

# Adjust these to your actual libraries. Add/remove as needed.
DEFAULT_LIBRARIES = [
    "/nfs/multimedia/data/media/movies",
    "/nfs/multimedia/data/media/tv",
    "/nfs/multimedia/data/media/music",
    "/nfs/multimedia/data/media/reading",
    "/nfs/multimedia/data/media/pdf",
]

MEDIA_EXTS = {
    "video": {".mkv", ".mp4", ".avi", ".mov", ".m4v"},
    "audio": {".flac", ".mp3", ".aac", ".m4a", ".ogg"},
    "book":  {".epub", ".pdf", ".mobi", ".azw3", ".cbz", ".cbr"},
    "other": set(),
}
ALL_EXTS = set().union(*MEDIA_EXTS.values())

IGNORE_DIR_PATTERNS = re.compile(r"(?i)(/sample[s]?/|/extras?/|/proofs?/|/subs?/)")
IGNORE_FILE_PATTERNS = re.compile(r"(?i)\.(nfo|sfv|srt|ass|idx|sub|jpg|jpeg|png|gif|txt)$")

# Common scene/release tokens and metadata to strip when normalizing names
TOKEN_PAT = re.compile(
    r"(?i)"
    r"(\b(1080p|2160p|720p|480p|4k|hdr10|dv|dovi|hevc|x264|x265|h\.?264|h\.?265|"
    r"remux|bluray|webrip|web-dl|br?rip|dvdrip|proper|internal|repack|extended|"
    r"readnfo|limited|complete|multi|dual|imd[bB]\d+|tmdb\d+)\b)|"
    r"(\[.*?\]|\(.*?\)|\{.*?\})|"
    r"(-\w+$)"
)

SPACE_PAT = re.compile(r"[._]+")
MULTISPACE_PAT = re.compile(r"\s+")

def human_bytes(n: int) -> str:
    units = ["B","KB","MB","GB","TB","PB"]
    s = 0
    f = float(n)
    while f >= 1024 and s < len(units)-1:
        f /= 1024.0
        s += 1
    return f"{f:.2f} {units[s]}"

def norm_name(path: str) -> str:
    base = os.path.basename(path)
    name, _ext = os.path.splitext(base)
    name = SPACE_PAT.sub(" ", name)
    name = TOKEN_PAT.sub(" ", name)
    name = MULTISPACE_PAT.sub(" ", name).strip().lower()
    return name

def file_ok(path: str) -> bool:
    if IGNORE_DIR_PATTERNS.search(path.replace("\\","/")):
        return False
    if IGNORE_FILE_PATTERNS.search(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in ALL_EXTS

def scan(paths):
    files = []
    total_bytes = 0
    newest_ts = 0
    for root in paths:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    if not file_ok(p):
                        continue
                    st = os.stat(p)
                except Exception:
                    continue
                files.append(p)
                total_bytes += st.st_size
                if st.st_mtime > newest_ts:
                    newest_ts = st.st_mtime
    return files, total_bytes, newest_ts

def build_index(paths):
    files, total_bytes, newest_ts = scan(paths)
    index = defaultdict(list)  # norm_name -> [paths]
    sizes = {}
    for p in files:
        n = norm_name(p)
        index[n].append(p)
        sizes[p] = os.path.getsize(p)
    return {
        "files": files,
        "bytes": sum(sizes.values()),
        "newest": newest_ts,
        "index": index,
        "sizes": sizes,
    }

def compare(ingest_idx, library_idx):
    lib_keys = set(library_idx["index"].keys())
    rows = []
    backlog = []

    for src, info in ingest_idx.items():
        files = info["files"]
        matched = 0
        unmatched = 0
        for p in files:
            key = norm_name(p)
            if key in lib_keys:
                matched += 1
            else:
                unmatched += 1
                backlog.append(p)

        total = len(files)
        pct = (matched / total * 100.0) if total else 0.0
        rows.append(
            Row(
                source=src,
                files=total,
                bytes=info["bytes"],
                matched=matched,
                unmatched=unmatched,
                pct_matched=pct,
            )
        )
    return rows, backlog

def _classify_ext(ext: str) -> str:
    """Return media type name for an extension, default 'other'."""
    ext = ext.lower()
    for t, exts in MEDIA_EXTS.items():
        if ext in exts:
            return t
    return "other"

def print_unprocessed_breakdown(backlog):
    """
    Print counts of unprocessed files by media type and by extension.
    Handles permission errors when reading file sizes.
    """
    if not backlog:
        print("\nNo unprocessed files to summarize.")
        return

    type_counts = defaultdict(int)
    ext_counts = defaultdict(int)
    type_bytes = defaultdict(int)
    total = 0

    for p in backlog:
        total += 1
        ext = os.path.splitext(p)[1].lower() or "<noext>"
        media_type = _classify_ext(ext)
        ext_counts[ext] += 1
        type_counts[media_type] += 1
        try:
            type_bytes[media_type] += os.path.getsize(p)
        except Exception:
            # Ignore size errors (permission, broken symlink, etc.)
            pass

    # Print media type breakdown
    print("\nUnprocessed files by media type:")
    print("-" * 48)
    print(f"{'Type':20} {'Count':>8} {'Pct':>7} {'Size':>11}")
    print("-" * 48)
    for t, cnt in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / total) * 100.0 if total else 0.0
        size_str = human_bytes(type_bytes.get(t, 0)) if type_bytes.get(t, 0) else "-"
        print(f"{t:20} {cnt:8d} {pct:7.1f}% {size_str:>11}")
    print("-" * 48)

    # Print extension breakdown (top extensions)
    print("\nUnprocessed files by extension (top):")
    print("-" * 40)
    print(f"{'Ext':8} {'Count':>8} {'Pct':>7}")
    print("-" * 40)
    for ext, cnt in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (cnt / total) * 100.0 if total else 0.0
        print(f"{ext:8} {cnt:8d} {pct:7.1f}%")
    print("-" * 40)

def write_unprocessed_listing(ext, backlog, out_dir="."):
    """
    Write a listing file in out_dir for unprocessed files matching `ext`.
    ext may be provided with or without leading dot.
    The file will be unprocessed_<ext>.txt and contain full paths, one per line.
    """
    if not ext:
        return
    ext_norm = ext if ext.startswith(".") else "." + ext
    ext_norm = ext_norm.lower()
    matches = [p for p in backlog if p.lower().endswith(ext_norm)]
    label = ext_norm.lstrip(".") or "noext"
    fname = os.path.join(out_dir, f"unprocessed_{label}.txt")
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(fname, "w", encoding="utf-8") as f:
            for p in matches:
                f.write(p + "\n")
        print(f"\nWrote {len(matches)} unprocessed '{ext_norm}' files to {os.path.abspath(fname)}")
    except Exception as e:
        print(f"Error writing listing {fname}: {e}")

def write_unprocessed_all(backlog, out_dir="."):
    """
    Write separate listing files for every extension present in the backlog.
    Files are written into out_dir with the pattern: unprocessed_<extlabel>.txt
    where <extlabel> is 'mkv' for '.mkv' or 'noext' for no extension.
    """
    if not backlog:
        print("\nNo unprocessed files to write.")
        return

    groups = defaultdict(list)
    for p in backlog:
        ext = os.path.splitext(p)[1].lower() or "<noext>"
        groups[ext].append(p)

    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        print(f"Error creating output directory '{out_dir}': {e}")
        return

    total_written = 0
    for ext, paths in sorted(groups.items(), key=lambda x: x[0]):
        label = ext.lstrip(".") if ext != "<noext>" else "noext"
        fname = os.path.join(out_dir, f"unprocessed_{label}.txt")
        try:
            with open(fname, "w", encoding="utf-8") as f:
                for p in paths:
                    f.write(p + "\n")
            print(f"Wrote {len(paths)} files for extension '{ext}' -> {os.path.abspath(fname)}")
            total_written += len(paths)
        except Exception as e:
            print(f"Error writing {fname}: {e}")
    print(f"\nTotal unprocessed paths written across all extension files: {total_written}")

def print_table(rows, grand_ingest_bytes):
    # Prepare display strings and compute dynamic widths for neat alignment
    src_header = "Source"
    files_header = "Files"
    size_header = "Size"
    matched_header = "Matched"
    unproc_header = "Unproc"
    pct_header = "%Org"

    # Precompute size strings
    size_strs = [human_bytes(r.bytes) for r in rows]
    # Compute widths
    src_w = max(len(src_header), max((len(r.source) for r in rows), default=0))
    src_w = min(max(src_w, 20), 60)  # sensible bounds
    files_w = max(len(files_header), 6)
    size_w = max(len(size_header), max((len(s) for s in size_strs), default=len(size_header)))
    matched_w = max(len(matched_header), 6)
    unproc_w = max(len(unproc_header), 6)
    pct_w = max(len(pct_header), 4)

    # Build format strings
    header_fmt = f"{{:<{src_w}}} {{:>{files_w}}} {{:>{size_w}}} {{:>{matched_w}}} {{:>{unproc_w}}} {{:>{pct_w}}}"
    row_fmt =    f"{{:<{src_w}}} {{:>{files_w}d}} {{:>{size_w}}} {{:>{matched_w}d}} {{:>{unproc_w}d}} {{:>{pct_w}.1f}}"

    total_width = src_w + files_w + size_w + matched_w + unproc_w + pct_w + 5*1  # spaces between cols

    print("\nSummary")
    print("-" * total_width)
    print(header_fmt.format(src_header, files_header, size_header, matched_header, unproc_header, pct_header))
    print("-" * total_width)
    for r, sz in zip(rows, size_strs):
        print(row_fmt.format(r.source, r.files, sz, r.matched, r.unmatched, r.pct_matched))
    print("-" * total_width)
    total_files = sum(r.files for r in rows)
    total_bytes = sum(r.bytes for r in rows)
    total_matched = sum(r.matched for r in rows)
    total_unmatched = sum(r.unmatched for r in rows)
    pct = (total_matched / total_files * 100.0) if total_files else 0.0

    total_size_str = human_bytes(total_bytes)
    # Ensure total size fits the size column by possibly extending size_w for the total line
    if len(total_size_str) > size_w:
        size_w = len(total_size_str)
        header_fmt = f"{{:<{src_w}}} {{:>{files_w}}} {{:>{size_w}}} {{:>{matched_w}}} {{:>{unproc_w}}} {{:>{pct_w}}}"
        row_fmt =    f"{{:<{src_w}}} {{:>{files_w}d}} {{:>{size_w}}} {{:>{matched_w}d}} {{:>{unproc_w}d}} {{:>{pct_w}.1f}}"
        total_width = src_w + files_w + size_w + matched_w + unproc_w + pct_w + 5
        print("\n" + "-" * total_width)

    print(row_fmt.format("TOTAL", total_files, total_size_str, total_matched, total_unmatched, pct))
    if grand_ingest_bytes:
        print(f"\nIngest size on disk: {human_bytes(total_bytes)}")

def main():
    ap = argparse.ArgumentParser(description="Compare ingest downloads vs organized libraries.")
    ap.add_argument("--ingest", nargs="+", default=DEFAULT_INGEST, help="Ingest directories to scan")
    ap.add_argument("--library", nargs="+", default=DEFAULT_LIBRARIES, help="Organized library roots to scan")
    ap.add_argument("--out-csv", default=None, help="Write CSV summary here")
    ap.add_argument("--out-backlog", default=None, help="Write list of unprocessed ingest files here")
    ap.add_argument("--ext-list", dest="ext_list", default=None,
                    help="Write listing of unprocessed files matching extension into current dir (e.g. --ext-list mkv or .mkv)")
    ap.add_argument("--ext-list-all", dest="ext_list_all", action="store_true",
                    help="Write per-extension unprocessed listings for all extensions found in the backlog")
    ap.add_argument("--ext-list-dir", dest="ext_list_dir", default=".",
                    help="Directory to write per-extension listings into (default: current dir)")
    ap.add_argument("--staging-dir", dest="staging_dir", default="/nfs/multimedia/data/to-remove",
                    help="Directory to move selected files into for staging (default: /nfs/multimedia/data/to-remove)")
    ap.add_argument("--move-ingest", dest="move_ingest", action="store_true",
                    help="If set, move ingest files into the staging directory")
    ap.add_argument("--move-libraries", dest="move_libraries", action="store_true",
                    help="If set, move library files into the staging directory")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="If set, show what would be moved but do not perform moves")
    args = ap.parse_args()

    # Build library index once
    lib_idx = build_index(args.library)

    # Build per-ingest indexes
    ingest_idx = {}
    for src in args.ingest:
        ingest_idx[src] = build_index([src])

    rows, backlog = compare(ingest_idx, lib_idx)

    # Capture printed summary and related output into a timestamped summary file.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_table(rows, sum(r.bytes for r in rows))

        if args.out_csv:
            import csv
            with open(args.out_csv, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["source","files","size_bytes","matched","unprocessed","pct_organized"])
                for r in rows:
                    w.writerow([r.source, r.files, r.bytes, r.matched, r.unmatched, f"{r.pct_matched:.1f}"])
            print(f"\nCSV: {args.out_csv}")

        if args.out_backlog:
            with open(args.out_backlog, "w") as f:
                for p in backlog:
                    f.write(p + "\n")
            print(f"Backlog list: {args.out_backlog}")

        # Print a breakdown of unprocessed file types and extensions
        print_unprocessed_breakdown(backlog)

        # Optionally write a listing for a specific extension into the current directory
        if args.ext_list:
            write_unprocessed_listing(args.ext_list, backlog, out_dir=args.ext_list_dir)

        # Optionally write per-extension listings for all extensions found
        if args.ext_list_all:
            write_unprocessed_all(backlog, out_dir=args.ext_list_dir)

        # Bonus: show newest timestamps
        newest = {}
        for src, info in ingest_idx.items():
            if info["newest"]:
                newest[src] = datetime.fromtimestamp(info["newest"]).isoformat(sep=" ", timespec="seconds")
        if newest:
            print("\nNewest item per ingest dir:")
            for src, ts in newest.items():
                print(f"- {src}: {ts}")

        # The staging/move block may print additional lines; run it inside the capture
        # Try to import tqdm for a nicer progress bar; fall back to simple print_progress
        try:
            from tqdm import tqdm
            HAVE_TQDM = True
        except Exception:
            tqdm = None
            HAVE_TQDM = False

        if args.staging_dir and (args.move_ingest or args.move_libraries):
            # Simple progress bar helper for move operations (prints counts and percent)
            def print_progress(done, total, moved, errors, prefix=""):
                try:
                    pct = (done / total * 100.0) if total else 100.0
                    bar_len = 30
                    filled = int(round(bar_len * done / float(total))) if total else bar_len
                    bar = "#" * filled + "-" * (bar_len - filled)
                    msg = f"{prefix}[{bar}] {done}/{total} ({pct:5.1f}%) moved={moved} errors={errors}"
                    # Print with carriage return to update in-place; flush so captured buffer gets it.
                    print(msg, end="\r", flush=True)
                    if done == total:
                        print()  # finish the line
                except Exception:
                    # Don't let progress printing break the move loop
                    pass
            # existing staging logic follows (safe_move, moves, etc.)
            def safe_move(src_path, dest_dir, dry_run=False):
                """Move src_path into dest_dir, handling name collisions by appending suffixes.
                Returns (True, dest_path) on success, (False, error_message) on failure."""
                try:
                    # In dry-run mode we won't create directories or move files; just report
                    base = os.path.basename(src_path)
                    dest = os.path.join(dest_dir, base)
                    if dry_run:
                        return True, dest  # indicate success for preview purposes
                    os.makedirs(dest_dir, exist_ok=True)
                    if not os.path.exists(dest):
                        shutil.move(src_path, dest)
                        return True, dest
                    # collision: append numeric suffix
                    name, ext = os.path.splitext(base)
                    for i in range(1, 1000):
                        candidate = os.path.join(dest_dir, f"{name}-{i}{ext}")
                        if not os.path.exists(candidate):
                            shutil.move(src_path, candidate)
                            return True, candidate
                    return False, f"name-collision: {base}"
                except PermissionError as pe:
                    # Try to add owner-write permission and retry once
                    try:
                        cur_mode = os.stat(src_path).st_mode
                        os.chmod(src_path, cur_mode | stat.S_IWUSR)
                        # ensure dest dir exists
                        os.makedirs(dest_dir, exist_ok=True)
                        if not os.path.exists(dest):
                            shutil.move(src_path, dest)
                            return True, dest
                        name, ext = os.path.splitext(base)
                        for i in range(1, 1000):
                            candidate = os.path.join(dest_dir, f"{name}-{i}{ext}")
                            if not os.path.exists(candidate):
                                shutil.move(src_path, candidate)
                                return True, candidate
                        return False, f"name-collision-after-chmod: {base}"
                    except Exception as e2:
                        return False, f"perm-denied: {pe} -> {e2}"
                except Exception as e:
                    return False, str(e)

            moved = 0
            move_errors = 0
            print(f"\nStaging to: {args.staging_dir}")
            # In dry-run mode do not create the root staging dir; just preview
            if not args.dry_run:
                try:
                    os.makedirs(args.staging_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error: could not create staging dir '{args.staging_dir}': {e}")
                    print("Skipping staging move.")
            else:
                print("Dry-run: not creating staging directory; no files will be moved.")

            # Move ingest files with progress
            if args.move_ingest:
                # Build a flat list of (p, dest_dir) so we can show progress across all ingest files
                ingest_tasks = []
                for src, info in ingest_idx.items():
                    sub = os.path.basename(src.rstrip(os.sep)) or "ingest"
                    dest_dir = os.path.join(args.staging_dir, "ingest", sub)
                    for p in info.get("files", []):
                        ingest_tasks.append((p, dest_dir))
                total_tasks = len(ingest_tasks)
                done = 0
                iterator = ingest_tasks
                if HAVE_TQDM:
                    iterator = tqdm(ingest_tasks, desc="Ingest", unit="file")
                for p, dest_dir in iterator:
                    ok, res = safe_move(p, dest_dir, dry_run=args.dry_run)
                    if ok:
                        moved += 1
                        if args.dry_run:
                            print(f"DRY-RUN: would move: {p} -> {res}")
                    else:
                        move_errors += 1
                        print(f"Move error (ingest): {p} -> {res}")
                    if not HAVE_TQDM:
                        done += 1
                        print_progress(done, total_tasks, moved, move_errors, prefix="Ingest: ")

            # Move library files with progress
            if args.move_libraries:
                lib_tasks = []
                for root in args.library:
                    idx = build_index([root])
                    sub = os.path.basename(root.rstrip(os.sep)) or "library"
                    dest_dir = os.path.join(args.staging_dir, "library", sub)
                    for p in idx.get("files", []):
                        lib_tasks.append((p, dest_dir))
                total_tasks = len(lib_tasks)
                done = 0
                iterator = lib_tasks
                if HAVE_TQDM:
                    iterator = tqdm(lib_tasks, desc="Library", unit="file")
                for p, dest_dir in iterator:
                    ok, res = safe_move(p, dest_dir, dry_run=args.dry_run)
                    if ok:
                        moved += 1
                        if args.dry_run:
                            print(f"DRY-RUN: would move: {p} -> {res}")
                    else:
                        move_errors += 1
                        print(f"Move error (library): {p} -> {res}")
                    if not HAVE_TQDM:
                        done += 1
                        print_progress(done, total_tasks, moved, move_errors, prefix="Library: ")

            print(f"Staging complete: moved={moved}, errors={move_errors}")

    # Write the captured output to a timestamped file
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = args.staging_dir if args.staging_dir and not args.dry_run else "."
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = "."
    summary_fname = os.path.join(out_dir, f"compare_summary_{timestamp}.txt")
    try:
        with open(summary_fname, "w", encoding="utf-8") as sf:
            sf.write(buf.getvalue())
        print(f"Wrote summary: {os.path.abspath(summary_fname)}")
    except Exception as e:
        print(f"Error writing summary file: {e}")

    if args.out_csv:
        import csv
        with open(args.out_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["source","files","size_bytes","matched","unprocessed","pct_organized"])
            for r in rows:
                w.writerow([r.source, r.files, r.bytes, r.matched, r.unmatched, f"{r.pct_matched:.1f}"])
        print(f"\nCSV: {args.out_csv}")

    if args.out_backlog:
        with open(args.out_backlog, "w") as f:
            for p in backlog:
                f.write(p + "\n")
        print(f"Backlog list: {args.out_backlog}")

    # Print a breakdown of unprocessed file types and extensions
    print_unprocessed_breakdown(backlog)

    # Optionally write a listing for a specific extension into the current directory
    if args.ext_list:
        write_unprocessed_listing(args.ext_list, backlog, out_dir=args.ext_list_dir)

    # Optionally write per-extension listings for all extensions found
    if args.ext_list_all:
        write_unprocessed_all(backlog, out_dir=args.ext_list_dir)

    # Bonus: show newest timestamps
    newest = {}
    for src, info in ingest_idx.items():
        if info["newest"]:
            newest[src] = datetime.fromtimestamp(info["newest"]).isoformat(sep=" ", timespec="seconds")
    if newest:
        print("\nNewest item per ingest dir:")
        for src, ts in newest.items():
            print(f"- {src}: {ts}")

        # Optionally move files into a staging directory
        if args.staging_dir and (args.move_ingest or args.move_libraries):
            # Simple progress bar helper for move operations (prints counts and percent)
            def print_progress(done, total, moved, errors, prefix=""):
                try:
                    pct = (done / total * 100.0) if total else 100.0
                    bar_len = 30
                    filled = int(round(bar_len * done / float(total))) if total else bar_len
                    bar = "#" * filled + "-" * (bar_len - filled)
                    msg = f"{prefix}[{bar}] {done}/{total} ({pct:5.1f}%) moved={moved} errors={errors}"
                    print(msg, end="\r", flush=True)
                    if done == total:
                        print()
                except Exception:
                    pass

            def safe_move(src_path, dest_dir, dry_run=False):
                """Move src_path into dest_dir, handling name collisions by appending suffixes.
                Returns (True, dest_path) on success, (False, error_message) on failure."""
                try:
                    # In dry-run mode we won't create directories or move files; just report
                    base = os.path.basename(src_path)
                    dest = os.path.join(dest_dir, base)
                    if dry_run:
                        # log preview
                        # log_move(src_path, dest, "preview", "")
                        return True, dest  # indicate success for preview purposes
                    os.makedirs(dest_dir, exist_ok=True)
                    if not os.path.exists(dest):
                        shutil.move(src_path, dest)
                        return True, dest
                    # collision: append numeric suffix
                    name, ext = os.path.splitext(base)
                    for i in range(1, 1000):
                        candidate = os.path.join(dest_dir, f"{name}-{i}{ext}")
                        if not os.path.exists(candidate):
                            shutil.move(src_path, candidate)
                            # log_move(src_path, candidate, "moved", "")
                            return True, candidate
                    # # log_move(src_path, dest, "error", f"name-collision: {base}")
                    return False, f"name-collision: {base}"
                except PermissionError as pe:
                    # Try to add owner-write permission and retry once
                    try:
                        cur_mode = os.stat(src_path).st_mode
                        os.chmod(src_path, cur_mode | stat.S_IWUSR)
                        # ensure dest dir exists
                        os.makedirs(dest_dir, exist_ok=True)
                        if not os.path.exists(dest):
                            shutil.move(src_path, dest)
                            return True, dest
                        name, ext = os.path.splitext(base)
                        for i in range(1, 1000):
                            candidate = os.path.join(dest_dir, f"{name}-{i}{ext}")
                            if not os.path.exists(candidate):
                                shutil.move(src_path, candidate)
                                return True, candidate
                        return False, f"name-collision-after-chmod: {base}"
                    except Exception as e2:
                        # # log_move(src_path, dest, "error", f"perm-denied: {pe} -> {e2}")
                        return False, f"perm-denied: {pe} -> {e2}"
                except Exception as e:
                    # # log_move(src_path, dest, "error", str(e))
                    return False, str(e)

            # # log_move is defined above in the enclosing scope; use that shared helper

            moved = 0
            move_errors = 0
            print(f"\nStaging to: {args.staging_dir}")
            # In dry-run mode do not create the root staging dir; just preview
            if not args.dry_run:
                try:
                    os.makedirs(args.staging_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error: could not create staging dir '{args.staging_dir}': {e}")
                    print("Skipping staging move.")
                    return 1
            else:
                print("Dry-run: not creating staging directory; no files will be moved.")

            # Move ingest files with progress
            if args.move_ingest:
                ingest_tasks = []
                for src, info in ingest_idx.items():
                    sub = os.path.basename(src.rstrip(os.sep)) or "ingest"
                    dest_dir = os.path.join(args.staging_dir, "ingest", sub)
                    for p in info.get("files", []):
                        ingest_tasks.append((p, dest_dir))
                total_tasks = len(ingest_tasks)
                iterator = ingest_tasks
                if HAVE_TQDM:
                    iterator = tqdm(ingest_tasks, desc="Ingest", unit="file")
                done = 0
                for p, dest_dir in iterator:
                    ok, res = safe_move(p, dest_dir, dry_run=args.dry_run)
                    if ok:
                        moved += 1
                        if args.dry_run:
                            print(f"DRY-RUN: would move: {p} -> {res}")
                    else:
                        move_errors += 1
                        print(f"Move error (ingest): {p} -> {res}")
                    if not HAVE_TQDM:
                        done += 1
                        print_progress(done, total_tasks, moved, move_errors, prefix="Ingest: ")

            # Move library files with progress
            if args.move_libraries:
                lib_tasks = []
                for root in args.library:
                    idx = build_index([root])
                    sub = os.path.basename(root.rstrip(os.sep)) or "library"
                    dest_dir = os.path.join(args.staging_dir, "library", sub)
                    for p in idx.get("files", []):
                        lib_tasks.append((p, dest_dir))
                total_tasks = len(lib_tasks)
                iterator = lib_tasks
                if HAVE_TQDM:
                    iterator = tqdm(lib_tasks, desc="Library", unit="file")
                done = 0
                for p, dest_dir in iterator:
                    ok, res = safe_move(p, dest_dir, dry_run=args.dry_run)
                    if ok:
                        moved += 1
                        if args.dry_run:
                            print(f"DRY-RUN: would move: {p} -> {res}")
                    else:
                        move_errors += 1
                        print(f"Move error (library): {p} -> {res}")
                    if not HAVE_TQDM:
                        done += 1
                        print_progress(done, total_tasks, moved, move_errors, prefix="Library: ")

            print(f"Staging complete: moved={moved}, errors={move_errors}")

if __name__ == "__main__":
    sys.exit(main())
