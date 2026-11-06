"""Collect up to 30,000 rated Lichess games per time control without unpacking a monthly archive.

Install: python -m pip install requests zstandard
Run:     python 02_lichess_stratified_sample.py

The default MODE="stream" streams the October 2026 archive and stops after reaching
its quotas; the 31GB .zst is NOT saved. For a whole-month random reservoir sample,
use MODE="local_reservoir" with an already downloaded archive.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ---------- SETTINGS ----------
MONTH = "2026-10"
QUOTA_PER_CONTROL = 30_000       # For a short trial, change to 100
MODE = "stream"                  # "stream" or "local_reservoir"
LOCAL_ARCHIVE = Path(f"lichess_db_standard_rated_{MONTH}.pgn.zst")
PICK_ONE_IN = 3                  # Deterministic subsample; set 1 to collect faster
MIN_CLOCK_ANNOTATIONS = 20      # A quick quality filter, not a full PGN validation
OUTPUT_DIR = Path("data") / f"lichess_{MONTH}_balanced"
SOURCE_URL = (
    f"https://database.lichess.org/standard/"
    f"lichess_db_standard_rated_{MONTH}.pgn.zst"
)
TIME_CONTROLS = {"60+0": "1m", "300+0": "5m", "600+0": "10m"}
HEADERS_RE = re.compile(r'^\[([A-Za-z0-9_]+) "(.*)"\]$', re.MULTILINE)
# ------------------------------


def raw_games(lines):
    """Yield one raw PGN game at a time, using little memory.

    Official standard-rated Lichess dumps start each game with an Event tag.
    We intentionally preserve the untouched PGN for later verification.
    """
    record = []
    for line in lines:
        if line.startswith('[Event "') and record:
            yield "".join(record)
            record = [line]
        else:
            record.append(line)
    if record:
        yield "".join(record)


def read_tags(record):
    header = record.split("\n\n", 1)[0]
    return dict(HEADERS_RE.findall(header))


def game_id_from_headers(h):
    value = h.get("GameId") or h.get("Site", "")
    if not value:
        return ""
    return urlparse(value).path.rstrip("/").split("/")[-1]


def eligible(record, h):
    control = h.get("TimeControl")
    if control not in TIME_CONTROLS:
        return False
    if "rated" not in h.get("Event", "").lower():
        return False
    if h.get("Variant", "Standard").lower() not in {"standard", "chess"}:
        return False
    if h.get("WhiteTitle", "").upper() == "BOT" or h.get("BlackTitle", "").upper() == "BOT":
        return False
    try:
        if int(h.get("WhiteElo", "0")) <= 0 or int(h.get("BlackElo", "0")) <= 0:
            return False
    except ValueError:
        return False
    if record.count("[%clk ") < MIN_CLOCK_ANNOTATIONS:
        return False
    return bool(game_id_from_headers(h))


def deterministic_pick(game_id):
    digest = hashlib.blake2b(f"{MONTH}|{game_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % PICK_ONE_IN == 0


def record_metadata(h, clock_count):
    return {
        "game_id": game_id_from_headers(h),
        "date": h.get("UTCDate", h.get("Date", "")),
        "time_control": h.get("TimeControl", ""),
        "initial_time_s": int(h["TimeControl"].split("+")[0]),
        "white_elo": h.get("WhiteElo", ""),
        "black_elo": h.get("BlackElo", ""),
        "result": h.get("Result", ""),
        "clock_annotations": clock_count,
        "source_month": MONTH,
    }


def compressed_text_reader():
    """Provide a text stream from the remote file or local .zst.

    Caller must close the returned context managers. All reads are streaming.
    """
    import zstandard as zstd
    if MODE == "stream":
        import requests
        response = requests.get(
            SOURCE_URL,
            stream=True,
            timeout=(30, 120),
            headers={"Accept-Encoding": "identity", "User-Agent": "DSF-student-research/0.1"},
        )
        response.raise_for_status()
        source = response.raw
        # The response closes when we close the underlying source below.
        close_source = response.close
    elif MODE == "local_reservoir":
        if not LOCAL_ARCHIVE.is_file():
            raise FileNotFoundError(f"Download {SOURCE_URL} to {LOCAL_ARCHIVE} first.")
        source = LOCAL_ARCHIVE.open("rb")
        close_source = source.close
    else:
        raise ValueError("MODE must be 'stream' or 'local_reservoir'")
    try:
        reader = zstd.ZstdDecompressor().stream_reader(source, read_across_frames=True)
        text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        return text, close_source
    except Exception:
        close_source()
        raise


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    count = Counter({tc: 0 for tc in TIME_CONTROLS})
    scanned = 0
    accepted = set()
    filenames = {tc: OUTPUT_DIR / f"games_{name}.pgn" for tc, name in TIME_CONTROLS.items()}
    metadata_csv = OUTPUT_DIR / "games_metadata.csv"
    fields = list(record_metadata({"TimeControl": "60+0"}, 0))
    complete = False

    if MODE == "local_reservoir":
        # Uniform reservoir selection within each stratum over the WHOLE archive.
        import random
        rng = random.Random(2026)
        reservoirs = {tc: [] for tc in TIME_CONTROLS}
        seen_per_control = Counter()
        text, close_source = compressed_text_reader()
        try:
            for record in raw_games(text):
                scanned += 1
                h = read_tags(record)
                if not eligible(record, h):
                    continue
                gid = game_id_from_headers(h)
                if not deterministic_pick(gid):
                    continue
                tc = h["TimeControl"]
                seen_per_control[tc] += 1
                n = seen_per_control[tc]
                item = (gid, record, record_metadata(h, record.count("[%clk ")))
                if len(reservoirs[tc]) < QUOTA_PER_CONTROL:
                    reservoirs[tc].append(item)
                else:
                    j = rng.randrange(n)
                    if j < QUOTA_PER_CONTROL:
                        reservoirs[tc][j] = item
                if scanned % 1_000_000 == 0:
                    print(f"Scanned {scanned:,} games; eligible seen: {dict(seen_per_control)}", flush=True)
        finally:
            text.close()
            close_source()
        with metadata_csv.open("w", newline="", encoding="utf-8") as mf:
            writer = csv.DictWriter(mf, fieldnames=fields)
            writer.writeheader()
            for tc, path in filenames.items():
                with path.open("w", encoding="utf-8") as pf:
                    for gid, record, meta in reservoirs[tc]:
                        pf.write(record.rstrip() + "\n\n")
                        writer.writerow(meta)
                        count[tc] += 1
        complete = all(count[tc] == QUOTA_PER_CONTROL for tc in TIME_CONTROLS)
    else:
        from contextlib import ExitStack
        with ExitStack() as stack:
            text, close_source = compressed_text_reader()
            stack.callback(close_source)
            stack.enter_context(text)
            outputs = {tc: stack.enter_context(path.open("w", encoding="utf-8")) for tc, path in filenames.items()}
            mf = stack.enter_context(metadata_csv.open("w", newline="", encoding="utf-8"))
            writer = csv.DictWriter(mf, fieldnames=fields)
            writer.writeheader()
            for record in raw_games(text):
                scanned += 1
                h = read_tags(record)
                tc = h.get("TimeControl")
                if tc not in TIME_CONTROLS or count[tc] >= QUOTA_PER_CONTROL:
                    continue
                if not eligible(record, h):
                    continue
                gid = game_id_from_headers(h)
                if gid in accepted or not deterministic_pick(gid):
                    continue
                accepted.add(gid)
                outputs[tc].write(record.rstrip() + "\n\n")
                writer.writerow(record_metadata(h, record.count("[%clk ")))
                count[tc] += 1
                if sum(count.values()) % 1000 == 0:
                    print(f"Saved {sum(count.values()):,} games: {dict(count)}", flush=True)
                if all(count[t] >= QUOTA_PER_CONTROL for t in TIME_CONTROLS):
                    complete = True
                    break
    manifest = {
        "source_url": SOURCE_URL, "month": MONTH, "mode": MODE,
        "quotas": {tc: QUOTA_PER_CONTROL for tc in TIME_CONTROLS},
        "counts": dict(count), "complete": complete, "games_scanned": scanned,
        "pick_one_in": PICK_ONE_IN,
        "min_clock_annotations": MIN_CLOCK_ANNOTATIONS,
        "utc_created": datetime.now(timezone.utc).isoformat(),
        "sampling_note": (
            "Streaming mode selects eligible games from the beginning of the month until quotas fill; "
            "not a uniformly random whole-month sample. Local reservoir mode samples the entire archive."
        ),
        "validation_note": "PGN syntax and clock coverage require downstream validation with python-chess.",
    }
    (OUTPUT_DIR / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if not complete:
        print("WARNING: quotas not met. Inspect source and filters before modelling.")


if __name__ == "__main__":
    run()
