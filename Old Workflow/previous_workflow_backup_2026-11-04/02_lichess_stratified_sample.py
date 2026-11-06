"""Stream a Lichess month; retain the lowest seeded hashes per time control.

Default: a capped pilot. Run --help for full-month and local archive examples.
No Stockfish, move features, labels or model training are performed here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import io
import json
import logging
import math
import re
import sqlite3
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import chess
import chess.pgn
import requests
import zstandard
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CONTROLS = {"60+0": "1m", "300+0": "5m", "600+0": "10m"}
TAG_RE = re.compile(r'^\[([A-Za-z0-9_]+) "(.*)"\]$', re.MULTILINE)
SITE_RE = re.compile(r"https://lichess\.org/(?:game/)?([A-Za-z0-9]{8})/?$")
RESULTS = {"1-0", "0-1", "1/2-1/2"}
FIELDS = ["game_id", "utc_date", "utc_time", "time_control", "initial_time_s",
          "white", "black", "white_elo", "black_elo", "result", "termination",
          "eco", "opening", "plies", "clock_annotations", "white_first_clock_s",
          "black_first_clock_s", "first_clock_below_nominal", "suspected_berserk",
          "clock_increases", "source_month", "source_record", "sampling_priority",
          "pgn_file", "pgn_index"]
LOG = logging.getLogger("lichess")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def raw_games(lines):
    """Keep original text; one PGN at a time (official exports use Event first)."""
    record = []
    size = 0
    for line in lines:
        if line.startswith('[Event "') and record:
            yield "".join(record)
            record, size = [], 0
        if not record and not line.strip():
            continue
        record.append(line)
        size += len(line)
        if size > 2_000_000:
            raise ValueError("PGN record exceeds 2 MB; check source framing")
    if record:
        yield "".join(record)


def read_tags(raw):
    return dict(TAG_RE.findall(raw.split("\n\n", 1)[0]))


def header_check(h, month):
    """Cheap filters before considering the hash; return a rejection reason."""
    if h.get("TimeControl") not in CONTROLS:
        return "other_time_control"
    if not h.get("Event", "").lower().startswith("rated "):
        return "not_rated"
    if h.get("Variant", "Standard") != "Standard" or "FEN" in h or "SetUp" in h:
        return "nonstandard_start"
    if any(h.get(c + "Title", "").upper() == "BOT" for c in ("White", "Black")):
        return "bot"
    if not SITE_RE.fullmatch(h.get("Site", "")):
        return "invalid_game_id"
    try:
        if any(int(h.get(c + "Elo", "0")) <= 0 for c in ("White", "Black")):
            return "invalid_elo"
        date = datetime.strptime(h.get("UTCDate", ""), "%Y.%m.%d")
        datetime.strptime(h.get("UTCTime", ""), "%H:%M:%S")
        if date.strftime("%Y-%m") != month:
            return "wrong_month"
    except ValueError:
        return "invalid_elo_or_date"
    if h.get("Result") not in RESULTS:
        return "unfinished_result"
    return None


def validate_game(raw, h, month):
    """Validate ALL mainline moves and clocks. Short finished games are allowed.

    A finished PGN may end by resignation: a terminal board is not required.
    Clock increases are retained and flagged (time gifts/corrections exist).
    """
    reason = header_check(h, month)
    if reason:
        return None, reason
    if raw.rstrip().split()[-1] != h["Result"]:
        return None, "missing_or_mismatched_movetext_result"
    try:
        # python-chess is deliberately forgiving and can skip unknown tokens.
        # Official exports have one mainline; require every move token to match it.
        movetext = raw.split("\n\n", 1)[1]
        movetext = re.sub(r"\{[^{}]*\}|;[^\n]*", " ", movetext)
        movetext = re.sub(r"\b\d+\.(?:\.\.)?", " ", movetext)
        movetext = re.sub(r"\$\d+", " ", movetext)
        tokens = movetext.split()
        if not tokens or tokens[-1] != h["Result"]:
            return None, "invalid_movetext"
        tokens = tokens[:-1]
        handle = io.StringIO(raw)
        game = chess.pgn.read_game(handle)
        if game is None or game.errors or chess.pgn.read_game(handle) is not None:
            return None, "pgn_parse_error"
        board = game.board()
        if board.fen() != chess.STARTING_FEN:
            return None, "nonstandard_start"
        initial = int(h["TimeControl"].split("+")[0])
        first, previous = {}, {}
        plies, increases = 0, 0
        nodes = list(game.mainline())
        if len(nodes) != len(tokens):
            return None, "unparsed_movetext"
        for node, token in zip(nodes, tokens):
            if not board.is_legal(node.move) or board.parse_san(token.rstrip("!?")) != node.move:
                return None, "illegal_move"
            clock = node.clock()
            if len(re.findall(r"\[%clk\b", node.comment)) != 1:
                return None, "missing_or_duplicate_clock"
            if clock is None or not math.isfinite(clock) or clock < 0:
                return None, "invalid_clock"
            side = "white" if board.turn == chess.WHITE else "black"
            first.setdefault(side, clock)
            if side in previous and clock > previous[side] + 0.05:
                increases += 1
            previous[side] = clock
            board.push(node.move)
            plies += 1
        if plies < 2:
            return None, "fewer_than_two_plies"
        # Checkmate/stalemate/etc. must agree; nonterminal resignations are fine.
        outcome = board.outcome(claim_draw=False)
        if outcome is not None and outcome.result() != h["Result"]:
            return None, "terminal_result_mismatch"
        meta = {
            "game_id": SITE_RE.fullmatch(h["Site"])[1],
            "utc_date": h["UTCDate"], "utc_time": h["UTCTime"],
            "time_control": h["TimeControl"], "initial_time_s": initial,
            "white": h.get("White", ""), "black": h.get("Black", ""),
            "white_elo": int(h["WhiteElo"]), "black_elo": int(h["BlackElo"]),
            "result": h["Result"], "termination": h.get("Termination", ""),
            "eco": h.get("ECO", ""), "opening": h.get("Opening", ""),
            "plies": plies, "clock_annotations": plies,
            "white_first_clock_s": first["white"], "black_first_clock_s": first["black"],
            "first_clock_below_nominal": any(c < initial - 1 for c in first.values()),
            "suspected_berserk": any(c <= initial / 2 + 1 for c in first.values()),
            "clock_increases": increases, "source_month": month,
        }
        return meta, None
    except (ValueError, IndexError, KeyError, AssertionError) as exc:
        return None, "invalid_pgn_" + type(exc).__name__


def priority_for(seed, month, game_id):
    return hashlib.sha256(f"{seed}|{month}|{game_id}".encode()).hexdigest()


def http_session():
    session = requests.Session()
    # Retry opening requests only. Never concatenate/restart a half-read zstd stream.
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update({"Accept-Encoding": "identity", "User-Agent": "DSF-chess-project/0.2"})
    return session


class MeasuredReader:
    def __init__(self, raw):
        self.raw, self.bytes_read = raw, 0
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.raw.read(size)
        self.bytes_read += len(chunk)
        self.digest.update(chunk)
        return chunk


@contextmanager
def source_text(args, manifest):
    """Integrity requires full compressed SHA256, not just decompressor EOF."""
    with http_session() as session:
        expected = args.expected_sha256
        archive_name = f"lichess_db_standard_rated_{args.month}.pgn.zst"
        url = f"https://database.lichess.org/standard/{archive_name}"
        is_compressed = args.local is None or args.local.suffix == ".zst"
        if is_compressed and not expected:
            response = session.get("https://database.lichess.org/standard/sha256sums.txt", timeout=(30, 120))
            response.raise_for_status()
            for line in response.text.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].lstrip("*") == archive_name:
                    expected = parts[0]
                    break
            if not expected:
                raise ValueError("Official checksum unavailable. Supply a trusted --expected-sha256.")
            manifest["checksum_source"] = "https://database.lichess.org/standard/sha256sums.txt"
        manifest["expected_source_sha256"] = expected
        response = None
        if args.local:
            raw = args.local.open("rb")
            total = args.local.stat().st_size
        else:
            response = session.get(url, stream=True, timeout=(30, 120))
            response.raise_for_status()
            raw = response.raw
            total = int(response.headers.get("Content-Length", "0")) or None
        measured = MeasuredReader(raw)
        manifest["source_size_bytes"] = total
        manifest["source_url"] = url
        manifest["local_path"] = str(args.local.resolve()) if args.local else None
        reader = zstandard.ZstdDecompressor().stream_reader(measured, read_across_frames=True, closefd=False) if is_compressed else None
        text = io.TextIOWrapper(reader or raw, encoding="utf-8", errors="strict", newline=None)
        try:
            yield text, measured
        finally:
            manifest["source_bytes_read"] = measured.bytes_read if is_compressed else raw.tell()
            manifest["source_sha256_read"] = measured.digest.hexdigest() if is_compressed else None
            text.close()
            raw.close()
            if response:
                response.close()


def write_json(path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_sample(db, output):
    counts, days = Counter(), Counter()
    with (output / "games_metadata.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for tc, label in CONTROLS.items():
            name = f"games_{label}.pgn"
            with (output / name).open("w", encoding="utf-8") as pgn:
                for index, (raw, encoded) in enumerate(db.execute(
                        "SELECT pgn, metadata FROM selected WHERE tc=? ORDER BY priority, game_id", (tc,)), 1):
                    meta = json.loads(encoded)
                    meta.update(pgn_file=name, pgn_index=index)
                    pgn.write(raw.rstrip() + "\n\n")
                    writer.writerow(meta)
                    counts[tc] += 1
                    days[tc + "/" + meta["utc_date"]] += 1
    return {tc: counts[tc] for tc in CONTROLS}, dict(sorted(days.items()))


def collect(args):
    """Heap keys in RAM, PGNs in SQLite. Memory does not grow with archive size.

    Only parse candidates beating the current worst VALID retained hash. A rejected
    game never consumes a slot; skipping larger hashes therefore cannot bias the
    final bottom-k sample of eligible games. Hash priorities are pseudorandom,
    seeded, and independent of archive order. Selected IDs are deduplicated.
    """
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty output directory: {output}")
    started = time.monotonic()
    stats, heaps = Counter(), {tc: [] for tc in CONTROLS}
    manifest = {
        "status": "running", "complete": False, "whole_source_read": False,
        "source_integrity_verified": False, "month": args.month, "seed": args.seed,
        "quota_per_control": args.quota, "max_games": args.max_games,
        "sampling": "lowest SHA256(seed|month|game_id) per time control; full source required",
        "validation": "legal standard-start mainline, finished matching result, positive Elo, clock on every ply; bots excluded",
        "clock_policy": "clock increases and suspected reduced starts retained with flags; annotations are POST-move",
        "utc_started": utc_now(), "counts": {tc: 0 for tc in CONTROLS},
        "versions": {p: version(p) for p in ("chess", "requests", "zstandard")},
        "python_version": sys.version.split()[0], "script_sha256": file_sha256(Path(__file__)),
    }
    path = output / "dataset_manifest.json"
    write_json(path, manifest)
    db = sqlite3.connect(output / "sampling_state.sqlite")
    db.execute("CREATE TABLE selected (game_id TEXT PRIMARY KEY, tc TEXT, priority TEXT, pgn TEXT, metadata TEXT)")
    db.execute("CREATE INDEX selected_tc_priority ON selected(tc, priority)")
    last_progress = time.monotonic()
    try:
        with source_text(args, manifest) as (text, measured):
            for raw in raw_games(text):
                stats["scanned"] += 1
                if time.monotonic() - last_progress >= args.progress_seconds:
                    elapsed = time.monotonic() - started
                    LOG.info("Scanned %s games; retained %s; %.1f games/s; %.1f MB read",
                             f'{stats["scanned"]:,}', {tc: len(h) for tc, h in heaps.items()},
                             stats["scanned"] / elapsed, measured.bytes_read / 1e6)
                    last_progress = time.monotonic()
                    db.commit()
                h = read_tags(raw)
                reason = header_check(h, args.month)
                if reason:
                    stats["header_reject/" + reason] += 1
                else:
                    tc = h["TimeControl"]
                    stats["header_candidates/" + tc] += 1
                    gid = SITE_RE.fullmatch(h["Site"])[1]
                    priority = priority_for(args.seed, args.month, gid)
                    number = int(priority, 16)
                    heap = heaps[tc]
                    if len(heap) == args.quota and number >= -heap[0][0]:
                        stats["hash_skipped"] += 1
                    elif db.execute("SELECT 1 FROM selected WHERE game_id=?", (gid,)).fetchone():
                        stats["duplicate_selected_id"] += 1
                    else:
                        stats["parsed_candidates"] += 1
                        meta, reason = validate_game(raw, h, args.month)
                        if reason:
                            stats["validation_reject/" + reason] += 1
                        else:
                            meta.update(source_record=stats["scanned"], sampling_priority=priority)
                            if len(heap) == args.quota:
                                _, removed = heapq.heappop(heap)
                                db.execute("DELETE FROM selected WHERE game_id=?", (removed,))
                            heapq.heappush(heap, (-number, gid))
                            db.execute("INSERT INTO selected VALUES (?, ?, ?, ?, ?)",
                                       (gid, tc, priority, raw, json.dumps(meta)))
                            stats["retained_insertions"] += 1
                if args.max_games and stats["scanned"] >= args.max_games:
                    break
            else:
                manifest["whole_source_read"] = True
        if manifest["whole_source_read"]:
            size = manifest["source_size_bytes"]
            if size is not None and manifest["source_bytes_read"] != size:
                raise ValueError("Source ended early: byte count differs from source size")
            expected = manifest["expected_source_sha256"]
            if expected:
                if manifest["source_sha256_read"] != expected:
                    raise ValueError("Source SHA256 mismatch (truncated, changed or wrong archive)")
                manifest["source_integrity_verified"] = True
        db.commit()
        manifest["counts"], manifest["selected_dates_by_control"] = export_sample(db, output)
        manifest["quotas_met"] = all(n == args.quota for n in manifest["counts"].values())
        manifest["complete"] = (manifest["whole_source_read"] and
                                manifest["source_integrity_verified"] and manifest["quotas_met"])
        manifest["status"] = "complete" if manifest["complete"] else "pilot_or_incomplete"
        names = ["games_metadata.csv"] + [f"games_{v}.pgn" for v in CONTROLS.values()]
        manifest["output_sha256"] = {name: file_sha256(output / name) for name in names}
    except BaseException as exc:
        manifest.update(status="failed", complete=False, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        db.commit()
        db.close()
        manifest.update(statistics=dict(stats), elapsed_seconds=round(time.monotonic() - started, 3), utc_finished=utc_now())
        write_json(path, manifest)
        LOG.info("%s: %s; %.1fs", manifest["status"], manifest["counts"], manifest["elapsed_seconds"])
    return manifest


def validate_outputs(output):
    """Independently replay exported PGNs and cross-check CSV, counts and hashes."""
    started = time.monotonic()
    manifest = json.loads((output / "dataset_manifest.json").read_text())
    issues, counts, seen = [], Counter(), set()
    with (output / "games_metadata.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    metadata = {row["game_id"]: row for row in rows}
    if len(metadata) != len(rows):
        issues.append("Duplicate game IDs in CSV")
    for name, expected in manifest.get("output_sha256", {}).items():
        if file_sha256(output / name) != expected:
            issues.append(f"Output checksum mismatch: {name}")
    for tc, label in CONTROLS.items():
        name = f"games_{label}.pgn"
        with (output / name).open(encoding="utf-8") as f:
            for index, raw in enumerate(raw_games(f), 1):
                counts[tc] += 1
                h = read_tags(raw)
                meta, reason = validate_game(raw, h, manifest["month"])
                if reason:
                    issues.append(f"{name} game {index}: {reason}")
                    continue
                gid = meta["game_id"]
                if gid in seen:
                    issues.append(f"Duplicate PGN game ID: {gid}")
                seen.add(gid)
                row = metadata.get(gid)
                if row is None:
                    issues.append(f"PGN game absent from CSV: {gid}")
                    continue
                meta.update(pgn_file=name, pgn_index=index,
                            sampling_priority=priority_for(manifest["seed"], manifest["month"], gid))
                for key, value in meta.items():
                    if str(value) != row.get(key):
                        issues.append(f"CSV mismatch {gid}: {key}")
                if meta["time_control"] != tc:
                    issues.append(f"Wrong stratum file: {gid}")
    if seen != set(metadata):
        issues.append("CSV and valid PGN game ID sets differ")
    actual = {tc: counts[tc] for tc in CONTROLS}
    if actual != manifest["counts"]:
        issues.append("PGN counts differ from manifest")
    report = {"valid": not issues, "counts": actual, "unique_valid_games": len(seen),
              "issue_count": len(issues), "issues_first_100": issues[:100],
              "elapsed_seconds": round(time.monotonic() - started, 3), "utc_checked": utc_now()}
    write_json(output / "validation_report.json", report)
    if issues:
        raise ValueError(f"Dataset validation failed: {len(issues)} issues; see validation_report.json")
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--quota", type=int, default=10, help="per time control (full dataset: 30000)")
    parser.add_argument("--max-games", type=int, default=20000, help="pilot cap; use 0 to read ALL games")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--local", type=Path, help="local .pgn.zst (recommended for full run) or .pgn fixture")
    parser.add_argument("--expected-sha256", help="trusted compressed checksum; default: official monthly checksum")
    parser.add_argument("--output", type=Path, default=Path("data/lichess_2026-10_pilot_v2"))
    parser.add_argument("--progress-seconds", type=float, default=10)
    parser.add_argument("--validate-only", action="store_true", help="replay PGNs and check CSV/manifest in --output")
    args = parser.parse_args(argv)
    try:
        datetime.strptime(args.month, "%Y-%m")
    except ValueError:
        parser.error("--month must be YYYY-MM")
    if args.quota <= 0 or args.max_games < 0 or args.progress_seconds <= 0:
        parser.error("quota/progress-seconds must be positive; max-games must be >=0")
    if args.expected_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256):
        parser.error("expected-sha256 must be 64 lowercase hexadecimal characters")
    return args


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)
    try:
        args = parse_args()
        if args.validate_only:
            print(json.dumps(validate_outputs(args.output), indent=2))
            sys.exit(0)
        result = collect(args)
    except (Exception, KeyboardInterrupt) as exc:
        LOG.error("Collection stopped: %s", exc)
        sys.exit(1)
    print(json.dumps({k: result[k] for k in ("status", "complete", "counts", "elapsed_seconds")}, indent=2))
    if result["whole_source_read"] and not result["quotas_met"]:
        sys.exit(2)
