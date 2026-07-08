# Ongoing Changes

## 2026-07-08

- Created backup snapshot `hikparser.pre_sparse_scan_backup.py` before additional parser edits.
- Updated `src/hikparser.py` `read_page_entries()` to improve sparse-entry recovery:
  - tightened plausibility checks (`channel` range, `data_offset` within disk size),
  - increased page scan depth,
  - added consecutive-invalid tolerance so scanning continues across gaps.
- Added resume-safe export behavior in `src/hikparser.py`:
  - writes into `YYYY-MM\YYYY-MM-DD` folders,
  - skips extraction when `.mp4` + `.md5` already exist,
  - supports legacy `_id_` naming detection per timestamp/channel.
- Added `reorganize_exports.py` with dry-run/apply modes and integrity report.
- Updated `README.md` with new layout, resume behavior and reorg commands.
- Validation against `03_Exports`:
  - before reorg: 811 `.mp4`, 811 `.md5`,
  - dry-run: 811 pairs movable, 0 unmatched, 0 parse failures,
  - apply: 811 pairs moved into date folders, 0 errors,
  - after reorg: 811 `.mp4`, 811 `.md5`.
- Added hybrid UNINDEX recovery feature:
  - new module `src/unindex_recovery.py` with `block`, `carve`, `hybrid` modes,
  - separate output tree in `UNINDEX` with best-effort date folders and fallback unknown folders,
  - writes `UNINDEX_CATALOG.csv` and resume checkpoint `scan_state.json`,
  - includes dedupe by processed offsets and md5 hash tracking.
- Updated `src/__main__.py`:
  - added `--unindex`, `--unindex-mode`, `--unindex-max`, `--carve-window` flags,
  - runs UNINDEX extraction after normal indexed extraction when enabled.
- Updated `README.md` with UNINDEX usage examples and output details.
