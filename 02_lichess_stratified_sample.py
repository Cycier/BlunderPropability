"""Collect a random sample of Lichess games. Edit the settings, then run."""

# 1. Imports and settings
import csv
import io
import json
import random
import time
from pathlib import Path

import chess.pgn
import requests
import zstandard

MONTH = "2026-10"
GAMES_PER_CONTROL = 30000    # Start small. Later: 30_000.
MAX_GAMES = 1000000           # Pilot only. Later: None to read the whole month.
SEED = 2026
OUTPUT_DIR = Path("data/simple_pilot")
LOCAL_ARCHIVE = None         # Or Path("lichess_db_standard_rated_2026-10.pgn.zst")

TIME_CONTROLS = {"60+0": "1m", "300+0": "5m", "600+0": "10m"}
SOURCE_URL = f"https://database.lichess.org/standard/lichess_db_standard_rated_{MONTH}.pgn.zst"
POOL_SIZE = int(GAMES_PER_CONTROL * 1.2)  # Keep 20% extra in case some games fail checks.


# 2. Read the text one game at a time
def read_games(lines):
    """In the official archive, each game starts with an [Event ...] line."""
    game_lines = []
    for line in lines:
        if line.startswith('[Event "') and game_lines:
            yield "".join(game_lines)
            game_lines = []
        game_lines.append(line)
    if game_lines:
        yield "".join(game_lines)


def read_headers(pgn):
    """Turn lines such as [TimeControl "60+0"] into a Python dictionary."""
    headers = {}
    for line in pgn.strip().splitlines():
        if not line.strip():
            break
        key, value = line[1:-1].split(" ", 1)
        headers[key] = value[1:-1]  # Remove the quotation marks.
    return headers


# 3. Decide which games are relevant
def usable_headers(headers):
    if headers.get("TimeControl") not in TIME_CONTROLS:
        return False
    if not headers.get("Event", "").startswith("Rated "):
        return False
    if headers.get("Variant", "Standard") != "Standard" or "FEN" in headers:
        return False
    if headers.get("WhiteTitle") == "BOT" or headers.get("BlackTitle") == "BOT":
        return False
    if headers.get("Result") not in ["1-0", "0-1", "1/2-1/2"]:
        return False
    if not headers.get("UTCDate", "").startswith(MONTH.replace("-", ".")):
        return False
    game_id = headers.get("Site", "").rstrip("/").split("/")[-1]
    if len(game_id) != 8 or not game_id.isalnum():
        return False
    try:
        return int(headers["WhiteElo"]) > 0 and int(headers["BlackElo"]) > 0
    except (KeyError, ValueError):
        return False


# 4. Keep a random sample while reading the archive
def sample_games(lines):
    rng = random.Random(SEED)
    samples = {control: [] for control in TIME_CONTROLS}
    eligible_seen = {control: 0 for control in TIME_CONTROLS}
    scanned = 0
    reached_end = True
    started = time.time()

    for pgn in read_games(lines):
        scanned += 1
        headers = read_headers(pgn)
        if usable_headers(headers):
            control = headers["TimeControl"]
            eligible_seen[control] += 1
            pool = samples[control]

            if len(pool) < POOL_SIZE:
                pool.append(pgn)
            else:
                # For the nth eligible game, choose a number from 0 to n-1.
                # Replace a saved game only if that number is inside the pool.
                # This gives every eligible game the same chance of being kept.
                position = rng.randrange(eligible_seen[control])
                if position < POOL_SIZE:
                    pool[position] = pgn

        if scanned % 10_000 == 0:
            print(f"Read {scanned:,} games in {time.time() - started:.0f}s; eligible: {eligible_seen}", flush=True)
        if MAX_GAMES is not None and scanned >= MAX_GAMES:
            reached_end = False
            break

    return samples, eligible_seen, scanned, reached_end


# 5. Check sampled games with python-chess
def check_game(pgn):
    """The parser checks legal moves; we check the result and every move's clock."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or game.errors:
        return None
    if pgn.strip().split()[-1] != game.headers.get("Result"):
        return None
    moves = 0
    for node in game.mainline():
        clock = node.clock()
        if clock is None or clock < 0:
            return None
        moves += 1
    if moves < 2 or pgn.count("[%clk ") != moves:
        return None
    outcome = game.end().board().outcome()
    if outcome is not None and outcome.result() != game.headers["Result"]:
        return None
    return moves


# 6. Save PGNs and one CSV row per game
def save_games(samples):
    rng = random.Random(SEED)
    counts = {control: 0 for control in TIME_CONTROLS}
    rejected = {control: 0 for control in TIME_CONTROLS}
    saved_ids = set()
    fields = ["game_id", "utc_date", "utc_time", "white", "black", "white_elo",
              "black_elo", "time_control", "result", "termination", "plies", "pgn_file"]

    with (OUTPUT_DIR / "games_metadata.csv").open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        for control, label in TIME_CONTROLS.items():
            pool = samples[control]
            rng.shuffle(pool)
            filename = f"games_{label}.pgn"
            with (OUTPUT_DIR / filename).open("w", encoding="utf-8") as pgn_file:
                for pgn in pool:
                    if counts[control] == GAMES_PER_CONTROL:
                        break
                    headers = read_headers(pgn)
                    game_id = headers["Site"].rstrip("/").split("/")[-1]
                    moves = check_game(pgn)
                    if moves is None or game_id in saved_ids:
                        rejected[control] += 1
                        continue
                    pgn_file.write(pgn.strip() + "\n\n")
                    writer.writerow({
                        "game_id": game_id, "utc_date": headers["UTCDate"],
                        "utc_time": headers.get("UTCTime", ""),
                        "white": headers.get("White", ""), "black": headers.get("Black", ""),
                        "white_elo": headers["WhiteElo"], "black_elo": headers["BlackElo"],
                        "time_control": control, "result": headers["Result"],
                        "termination": headers.get("Termination", ""),
                        "plies": moves, "pgn_file": filename,
                    })
                    saved_ids.add(game_id)
                    counts[control] += 1
            print(f"Saved {counts[control]:,} games for {control}")
    return counts, rejected


# 7. Open the compressed archive and run the steps above
def run():
    # A new folder prevents accidentally overwriting an earlier dataset.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    summary = {"status": "started", "source": SOURCE_URL, "month": MONTH,
               "seed": SEED, "games_per_control": GAMES_PER_CONTROL,
               "pool_size": POOL_SIZE, "max_games": MAX_GAMES,
               "source_checksum_checked_by_script": False,
               "local_archive": str(LOCAL_ARCHIVE) if LOCAL_ARCHIVE else None}
    response = None
    source = None
    try:
        if LOCAL_ARCHIVE is None:
            response = requests.get(SOURCE_URL, stream=True, timeout=(30, 120),
                                    headers={"Accept-Encoding": "identity"})
            response.raise_for_status()
            source = response.raw
        else:
            source = LOCAL_ARCHIVE.open("rb")

        with zstandard.ZstdDecompressor().stream_reader(source, read_across_frames=True) as reader:
            with io.TextIOWrapper(reader, encoding="utf-8") as text:
                samples, eligible, scanned, reached_end = sample_games(text)
                # A full remote read must match the server's advertised size.
                if reached_end and response is not None:
                    expected_size = response.headers.get("Content-Length")
                    if expected_size and source.tell() != int(expected_size):
                        raise ValueError("Download ended early. Run again in a new output folder.")

        counts, rejected = save_games(samples)
        enough_games = all(count == GAMES_PER_CONTROL for count in counts.values())
        status = "whole_source_sample" if reached_end and enough_games else "pilot_or_incomplete"
        summary.update(status=status, games_scanned=scanned, eligible_seen=eligible,
                       reached_end=reached_end, saved=counts, rejected_in_sample=rejected)
        if not enough_games:
            print("Not enough valid games. Increase the pool size or pilot scan limit and rerun.")
    except (Exception, KeyboardInterrupt) as error:
        summary.update(status="failed", error=str(error))
        raise
    finally:
        if source is not None:
            source.close()
        if response is not None:
            response.close()
        (OUTPUT_DIR / "collection_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Finished: {summary['status']}. Files are in {OUTPUT_DIR}")
    return summary


if __name__ == "__main__":
    run()
