import argparse
import os
import re
import shutil
from dataclasses import dataclass


FILENAME_RE = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}-"
    r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_ch_\d+_.*\.(?P<ext>mp4|md5)$",
    re.IGNORECASE
)


@dataclass
class Summary:
    moved_pairs: int = 0
    skipped_pairs: int = 0
    unmatched_mp4: int = 0
    unmatched_md5: int = 0
    parse_failed: int = 0
    errors: int = 0


def collect_files(root_dir):
    mp4_files = {}
    md5_files = {}
    parse_failed = []

    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            lowered = name.lower()
            if not (lowered.endswith(".mp4") or lowered.endswith(".md5")):
                continue
            full_path = os.path.join(dirpath, name)
            base_name = os.path.splitext(name)[0]
            match = FILENAME_RE.match(name)
            if not match:
                parse_failed.append(full_path)
                continue
            if lowered.endswith(".mp4"):
                mp4_files[base_name] = full_path
            else:
                md5_files[base_name] = full_path
    return mp4_files, md5_files, parse_failed


def build_target_paths(root_dir, mp4_path, md5_path):
    file_name = os.path.basename(mp4_path)
    match = FILENAME_RE.match(file_name)
    if not match:
        return None, None, None

    start_date = match.group("start")
    month_dir = start_date[:7]
    day_dir = start_date
    target_dir = os.path.join(root_dir, month_dir, day_dir)
    target_mp4 = os.path.join(target_dir, os.path.basename(mp4_path))
    target_md5 = os.path.join(target_dir, os.path.basename(md5_path))
    return target_dir, target_mp4, target_md5


def ensure_dir(path, dry_run):
    if dry_run:
        return
    os.makedirs(path, exist_ok=True)


def move_pair(mp4_src, md5_src, target_dir, mp4_dst, md5_dst, dry_run):
    src_mp4_norm = os.path.normcase(os.path.abspath(mp4_src))
    src_md5_norm = os.path.normcase(os.path.abspath(md5_src))
    dst_mp4_norm = os.path.normcase(os.path.abspath(mp4_dst))
    dst_md5_norm = os.path.normcase(os.path.abspath(md5_dst))

    already_in_place = src_mp4_norm == dst_mp4_norm and src_md5_norm == dst_md5_norm
    if already_in_place:
        return "skipped"

    if os.path.exists(mp4_dst) or os.path.exists(md5_dst):
        return "skipped"

    if not dry_run:
        ensure_dir(target_dir, dry_run=False)
        shutil.move(mp4_src, mp4_dst)
        shutil.move(md5_src, md5_dst)
    return "moved"


def run(root_dir, dry_run):
    summary = Summary()
    mp4_files, md5_files, parse_failed = collect_files(root_dir)
    summary.parse_failed = len(parse_failed)

    keys = sorted(set(mp4_files.keys()) | set(md5_files.keys()))
    for key in keys:
        mp4_path = mp4_files.get(key)
        md5_path = md5_files.get(key)

        if mp4_path is None:
            summary.unmatched_md5 += 1
            continue
        if md5_path is None:
            summary.unmatched_mp4 += 1
            continue

        target_dir, target_mp4, target_md5 = build_target_paths(root_dir, mp4_path, md5_path)
        if target_dir is None:
            summary.parse_failed += 1
            continue

        try:
            result = move_pair(mp4_path, md5_path, target_dir, target_mp4, target_md5, dry_run)
            if result == "moved":
                summary.moved_pairs += 1
            else:
                summary.skipped_pairs += 1
        except OSError:
            summary.errors += 1

    return summary


def main():
    parser = argparse.ArgumentParser(description="Reorganize extracted HikVision exports by month/day.")
    parser.add_argument("export_dir", help="Root export directory")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Default is dry-run."
    )
    args = parser.parse_args()

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"
    print("Mode:", mode)
    print("Export directory:", args.export_dir)

    summary = run(args.export_dir, dry_run=dry_run)
    print("moved_pairs:", summary.moved_pairs)
    print("skipped_pairs:", summary.skipped_pairs)
    print("unmatched_mp4:", summary.unmatched_mp4)
    print("unmatched_md5:", summary.unmatched_md5)
    print("parse_failed:", summary.parse_failed)
    print("errors:", summary.errors)


if __name__ == "__main__":
    main()
