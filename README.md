# HikVision Data Recovery

Script to recover / get video files from NVR hard drive which uses the HikVision filesystem. 

Based on the paper from Jaehyeok Han, Doowon Jeong and Sangjin Lee (Korean University)

https://www.researchgate.net/publication/285429692_Analysis_of_the_HIKVISION_DVR_file_system

You'll need a encase or dd image or access to a raw disk.

Usage:

__main__.py [-h] -m MODE -i INPUT -d DIR [--unindex] [--unindex-mode {block,carve,hybrid}] [--unindex-max N] [--carve-window MB]

optional arguments:
  -h, --help            show this help message and exit
  -m MODE, --mode MODE  Information (i) or extraction (e)
  -i INPUT, --input INPUT
                        Inputfile (.dd, .e01 or physical disk)
  -d DIR, --dir DIR     Output-Directory for logs and/or videos
  --unindex             Enable non-indexed extraction into UNINDEX folder
  --unindex-mode        UNINDEX strategy: block, carve or hybrid (default: hybrid)
  --unindex-max         Maximum UNINDEX files to create per run (0 = unlimited)
  --carve-window        Carve scan window in MB from video data start (default: 512)

Output of all tables (page list, information etc) in .csv files.

## Export layout and resume behavior

- Extracted videos are written to timestamp folders:
  - `DIR\YYYY-MM\YYYY-MM-DD\*.mp4`
  - `DIR\YYYY-MM\YYYY-MM-DD\*.md5`
- Basenames are deterministic and include start/end time, channel and block offset.
- Re-running extraction skips blocks when both `.mp4` and `.md5` already exist.

## UNINDEX recovery (non-indexed files)

- UNINDEX outputs are written under:
  - `DIR\UNINDEX\YYYY-MM\YYYY-MM-DD\...` (best-effort inferred time)
  - `DIR\UNINDEX\unknown\...` (fallback when timestamps cannot be inferred)
- UNINDEX writes:
  - media files (`.mp4` when MP4 detected, otherwise `.bin`),
  - paired `.md5` files,
  - `DIR\UNINDEX\UNINDEX_CATALOG.csv` with source offset, method and confidence,
  - `DIR\UNINDEX\scan_state.json` checkpoint for restart/resume.

Examples:

- Hybrid UNINDEX (recommended):
  - `python -m src -m e -i "image.dd" -d "X:\Exports" --unindex --unindex-mode hybrid`
- Block-scan only (faster):
  - `python -m src -m e -i "image.dd" -d "X:\Exports" --unindex --unindex-mode block`
- Bounded run for testing:
  - `python -m src -m e -i "image.dd" -d "X:\Exports" --unindex --unindex-max 25 --carve-window 128`

## Reorganize existing exports

Use the included script to move existing flat exports into `month/day` folders.

Dry-run:

`python reorganize_exports.py "X:\path\to\Exports"`

Apply changes:

`python reorganize_exports.py --apply "X:\path\to\Exports"`

The script reports moved/skipped pairs, unmatched files, and parse failures.

© 2024 Dane Wullen

Changes/updates by Todd DeSilva 2026

NO WARRANTY, SOFWARE IS PROVIDED 'AS IS'
