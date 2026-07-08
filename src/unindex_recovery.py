"""
Hybrid UNINDEX recovery helpers.
"""

import csv
import datetime
import hashlib
import json
import os
import re


class UnindexRecovery:
    def __init__(self, parser, export_dir, mode="hybrid", unindex_max=0, carve_window_mb=512):
        self.parser = parser
        self.export_dir = export_dir
        self.mode = mode
        self.unindex_max = int(unindex_max or 0)
        self.carve_window_mb = int(carve_window_mb or 512)

        self.unindex_root = os.path.join(self.export_dir, "UNINDEX")
        self.catalog_path = os.path.join(self.unindex_root, "UNINDEX_CATALOG.csv")
        self.state_path = os.path.join(self.unindex_root, "scan_state.json")

        self._ensure_dir(self.unindex_root)
        self._ensure_catalog()
        self.state = self._load_state()

    def _ensure_dir(self, path):
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)

    def _ensure_catalog(self):
        if os.path.isfile(self.catalog_path):
            return
        with open(self.catalog_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "method",
                "source_offset",
                "size_bytes",
                "signature",
                "confidence",
                "channel",
                "start_time_utc",
                "end_time_utc",
                "relative_output",
                "md5"
            ])

    def _load_state(self):
        default_state = {
            "block_next_index": 0,
            "carve_next_offset": None,
            "processed_offsets": [],
            "md5_seen": []
        }
        if not os.path.isfile(self.state_path):
            return default_state
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            default_state.update(loaded)
        except (OSError, json.JSONDecodeError):
            return default_state
        return default_state

    def _save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def _indexed_offsets(self):
        offsets = set()
        for page in self.parser.hikbtree.get_page_list():
            for block in page.data_blocks:
                offsets.add(int(block.data_offset))
        return offsets

    def _indexed_hints(self):
        hints = []
        for page in self.parser.hikbtree.get_page_list():
            for block in page.data_blocks:
                try:
                    start_dt = datetime.datetime.utcfromtimestamp(int(block.start_time))
                    end_dt = datetime.datetime.utcfromtimestamp(int(block.end_time))
                except (ValueError, OSError, OverflowError):
                    start_dt = None
                    end_dt = None
                hints.append({
                    "offset": int(block.data_offset),
                    "channel": int(block.channel),
                    "start": start_dt,
                    "end": end_dt
                })
        hints.sort(key=lambda x: x["offset"])
        return hints

    def _processed_offsets_set(self):
        return set(int(x) for x in self.state.get("processed_offsets", []))

    def _md5_seen_set(self):
        return set(self.state.get("md5_seen", []))

    def _add_processed_offset(self, offset):
        processed = self.state.setdefault("processed_offsets", [])
        processed.append(int(offset))
        if len(processed) > 250000:
            self.state["processed_offsets"] = processed[-250000:]

    def _add_seen_md5(self, md5_hash):
        seen = self.state.setdefault("md5_seen", [])
        seen.append(md5_hash)
        if len(seen) > 250000:
            self.state["md5_seen"] = seen[-250000:]

    def _decode_timestamp_from_name(self, name):
        match = re.match(
            r"^(?P<start>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-(?P<end>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})",
            name
        )
        if not match:
            return None, None
        start = datetime.datetime.strptime(match.group("start"), "%Y-%m-%d_%H-%M-%S")
        end = datetime.datetime.strptime(match.group("end"), "%Y-%m-%d_%H-%M-%S")
        return start, end

    def _best_effort_target_dir(self, start_dt=None, channel=None, offset=None):
        if start_dt is not None:
            month_dir = start_dt.strftime("%Y-%m")
            day_dir = start_dt.strftime("%Y-%m-%d")
            out = os.path.join(self.unindex_root, month_dir, day_dir)
            self._ensure_dir(out)
            return out

        if channel is not None:
            out = os.path.join(self.unindex_root, "unknown", "channel_{}".format(channel))
            self._ensure_dir(out)
            return out

        bucket = "offset_{}".format(int((offset or 0) // (1024 * 1024 * 1024)))
        out = os.path.join(self.unindex_root, "unknown", bucket)
        self._ensure_dir(out)
        return out

    def _looks_like_mp4(self, data):
        if len(data) < 16:
            return False
        if data[4:8] == b"ftyp":
            return True
        return b"ftyp" in data[:65536]

    def _looks_like_ts(self, data):
        if len(data) < (188 * 5):
            return False
        checks = 0
        for idx in range(0, 188 * 5, 188):
            if data[idx:idx + 1] == b"\x47":
                checks += 1
        return checks >= 4

    def _looks_like_nal_stream(self, data):
        # Very lightweight H26x heuristic.
        marker_count = data.count(b"\x00\x00\x01")
        return marker_count >= 10

    def _detect_signature(self, data):
        if self._looks_like_mp4(data):
            return "mp4", "high"
        if self._looks_like_ts(data):
            return "mpegts", "medium"
        if self._looks_like_nal_stream(data):
            return "h26x", "low"
        return None, None

    def _safe_filename(self, text):
        return re.sub(r"[^A-Za-z0-9._-]", "_", text)

    def _infer_metadata_from_offset(self, source_offset, hints):
        if not hints:
            return None, None, "none"
        nearest = min(hints, key=lambda h: abs(h["offset"] - source_offset))
        delta = abs(nearest["offset"] - source_offset)
        # Confidence tiers based on proximity to indexed region.
        if delta <= (8 * 1024 * 1024):
            confidence = "high"
        elif delta <= (64 * 1024 * 1024):
            confidence = "medium"
        else:
            confidence = "low"
        return nearest["channel"], nearest["start"], confidence

    def _write_output(self, method, source_offset, payload, signature, confidence, channel=None, start_dt=None, end_dt=None):
        target_dir = self._best_effort_target_dir(start_dt=start_dt, channel=channel, offset=source_offset)
        start_txt = start_dt.strftime("%Y-%m-%d_%H-%M-%S") if start_dt else "unknown_start"
        end_txt = end_dt.strftime("%Y-%m-%d_%H-%M-%S") if end_dt else "unknown_end"
        ext = "mp4" if signature == "mp4" else "bin"
        base = "{}-{}_ch_{}_off_{}_{}_{}".format(
            start_txt,
            end_txt,
            channel if channel is not None else "unk",
            source_offset,
            method,
            signature
        )
        base = self._safe_filename(base)

        media_path = os.path.join(target_dir, base + "." + ext)
        md5_path = os.path.join(target_dir, base + ".md5")

        if os.path.isfile(media_path) and os.path.isfile(md5_path):
            with open(md5_path, "r", encoding="utf-8") as f:
                digest = f.read().strip()
            return digest, media_path, True

        digest = hashlib.md5(payload).hexdigest()
        if digest in self._md5_seen_set():
            return digest, media_path, True

        with open(media_path, "wb") as f:
            f.write(payload)
        with open(md5_path, "w", encoding="utf-8") as f:
            f.write(digest)
        self._add_seen_md5(digest)
        return digest, media_path, False

    def _append_catalog(self, method, source_offset, size_bytes, signature, confidence, channel, start_dt, end_dt, media_path, md5_hash):
        rel_output = os.path.relpath(media_path, self.export_dir)
        with open(self.catalog_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                method,
                source_offset,
                size_bytes,
                signature,
                confidence,
                channel if channel is not None else "",
                start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else "",
                end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else "",
                rel_output,
                md5_hash
            ])

    def _extract_candidate(self, method, source_offset, payload, signature, confidence, channel=None, start_dt=None, end_dt=None):
        if signature is None:
            return False
        md5_hash, media_path, already = self._write_output(
            method=method,
            source_offset=source_offset,
            payload=payload,
            signature=signature,
            confidence=confidence,
            channel=channel,
            start_dt=start_dt,
            end_dt=end_dt
        )
        if already:
            return False
        self._append_catalog(
            method=method,
            source_offset=source_offset,
            size_bytes=len(payload),
            signature=signature,
            confidence=confidence,
            channel=channel,
            start_dt=start_dt,
            end_dt=end_dt,
            media_path=media_path,
            md5_hash=md5_hash
        )
        return True

    def _extract_unindexed_block_scan(self):
        indexed_offsets = self._indexed_offsets()
        processed_offsets = self._processed_offsets_set()
        hints = self._indexed_hints()

        base_offset = int(self.parser.master_sector.video_data_area_offset)
        block_size = int(self.parser.master_sector.data_block_size)
        total_blocks = int(self.parser.master_sector.data_block_total)
        start_index = int(self.state.get("block_next_index", 0))

        created = 0
        skipped = 0
        scanned = 0

        for block_index in range(start_index, total_blocks):
            if self.unindex_max and created >= self.unindex_max:
                break

            source_offset = base_offset + (block_index * block_size)
            self.state["block_next_index"] = block_index + 1

            if source_offset in indexed_offsets or source_offset in processed_offsets:
                skipped += 1
                if block_index % 64 == 0:
                    self._save_state()
                continue

            self.parser.diskimage.seek(source_offset)
            probe = self.parser.diskimage.read(min(1024 * 1024, block_size))
            signature, confidence = self._detect_signature(probe)
            scanned += 1

            if signature is None:
                self._add_processed_offset(source_offset)
                if block_index % 64 == 0:
                    self._save_state()
                continue

            self.parser.diskimage.seek(source_offset)
            payload = self.parser.diskimage.read(block_size)
            channel, start_dt, infer_confidence = self._infer_metadata_from_offset(source_offset, hints)
            if self._extract_candidate(
                    method="block_scan",
                    source_offset=source_offset,
                    payload=payload,
                    signature=signature,
                    confidence="{}+{}".format(confidence, infer_confidence),
                    channel=channel,
                    start_dt=start_dt,
                    end_dt=start_dt):
                created += 1
            self._add_processed_offset(source_offset)

            if block_index % 16 == 0:
                self._save_state()

        self._save_state()
        return {"scanned": scanned, "skipped": skipped, "created": created}

    def _extract_carve_pass(self):
        # Bounded carve pass from video data start over configured window.
        base_offset = int(self.parser.master_sector.video_data_area_offset)
        block_size = int(self.parser.master_sector.data_block_size)
        carve_limit = self.carve_window_mb * 1024 * 1024
        chunk_size = 4 * 1024 * 1024
        overlap = 64

        start_offset = self.state.get("carve_next_offset")
        if start_offset is None:
            start_offset = base_offset
        start_offset = int(start_offset)

        end_offset = base_offset + carve_limit
        if start_offset >= end_offset:
            return {"scanned_chunks": 0, "created": 0}

        created = 0
        scanned_chunks = 0
        processed_offsets = self._processed_offsets_set()
        hints = self._indexed_hints()

        offset = start_offset
        while offset < end_offset:
            read_len = min(chunk_size, end_offset - offset)
            self.parser.diskimage.seek(offset)
            chunk = self.parser.diskimage.read(read_len)
            scanned_chunks += 1

            # Signature scanning for likely starts.
            candidates = []
            pos = chunk.find(b"ftyp")
            if pos > 0:
                candidates.append((offset + pos - 4, "mp4", "medium"))

            # Basic TS sync periodic check at a few alignments.
            for base in range(0, min(188, len(chunk))):
                checks = 0
                for idx in range(base, min(base + (188 * 6), len(chunk)), 188):
                    if chunk[idx:idx + 1] == b"\x47":
                        checks += 1
                if checks >= 5:
                    candidates.append((offset + base, "mpegts", "low"))
                    break

            # H26x markers.
            nal_pos = chunk.find(b"\x00\x00\x01")
            if nal_pos >= 0:
                candidates.append((offset + nal_pos, "h26x", "low"))

            for candidate_offset, signature, confidence in candidates:
                if candidate_offset in processed_offsets:
                    continue
                self.parser.diskimage.seek(candidate_offset)
                payload = self.parser.diskimage.read(min(block_size, 64 * 1024 * 1024))
                detected_sig, detected_conf = self._detect_signature(payload[:1024 * 1024])
                if detected_sig is None:
                    self._add_processed_offset(candidate_offset)
                    continue
                channel, start_dt, infer_confidence = self._infer_metadata_from_offset(candidate_offset, hints)
                if self._extract_candidate(
                        method="carve",
                        source_offset=candidate_offset,
                        payload=payload,
                        signature=detected_sig,
                        confidence="{}+{}".format(detected_conf or confidence, infer_confidence),
                        channel=channel,
                        start_dt=start_dt,
                        end_dt=start_dt):
                    created += 1
                self._add_processed_offset(candidate_offset)

            offset += (chunk_size - overlap)
            self.state["carve_next_offset"] = offset
            if scanned_chunks % 8 == 0:
                self._save_state()

            if self.unindex_max and created >= self.unindex_max:
                break

        self._save_state()
        return {"scanned_chunks": scanned_chunks, "created": created}

    def run(self):
        print("UNINDEX mode: {}".format(self.mode))
        summary = {}

        if self.mode in ("block", "hybrid"):
            summary["block_scan"] = self._extract_unindexed_block_scan()
            print("UNINDEX block scan:", summary["block_scan"])

        if self.mode in ("carve", "hybrid"):
            summary["carve"] = self._extract_carve_pass()
            print("UNINDEX carve pass:", summary["carve"])

        print("UNINDEX catalog:", self.catalog_path)
        print("UNINDEX state:", self.state_path)
        return summary
