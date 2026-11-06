# Provides tools for reading and writing CSV files.
import csv
# Provides in-memory text and binary streams.
import io
# Provides tools for writing JSON files.
import json
# Provides reproducible random sampling.
import random
# Provides timing functions for progress reporting.
import time
# Provides convenient filesystem path handling.
from pathlib import Path

# Parses chess games stored in PGN format.
import chess.pgn
# Needed for downloading the remote Lichess archive.
import requests
# Decompresses the Zstandard archive.
import zstandard

# Selects the month of games to process.
MONTH = "2026-10"
# Sets the target number of games for each time control.
GAMES_PER_CONTROL = 30000   
# Limits how many games the pilot run scans.
MAX_GAMES = 120000           # Pilot only. Later: None to read the whole month.
# Makes random sampling reproducible between runs.
SEED = 2026
# Sets the folder where output files will be saved.
OUTPUT_DIR = Path("data")
# Uses a download unless a local archive path is provided.
LOCAL_ARCHIVE = None         # Or Path("lichess_db_standard_rated_2026-10.pgn.zst")

# Maps each accepted time control to a filename label.
TIME_CONTROLS = {"60+0": "1m", "300+0": "5m", "600+0": "10m"}
#Download URL for the selected month
SOURCE_URL = f"https://database.lichess.org/standard/lichess_db_standard_rated_{MONTH}.pgn.zst"
# Keeps extra candidates so validation can replace rejected games.
POOL_SIZE = int(GAMES_PER_CONTROL * 1.2)  # Keep 20% extra in case some games fail checks.

# Format of Lichess.pgn.zxt: one huge PGN file with all games concatenated. Each game starts with an [Event ...] line and ends with a blank line. Each game has a [TimeControl ...] header, and the clock for each move is stored in a [%clk ...] comment.

# 2. Read the text one game at a time, in the official archive, each game starts with an [Event ...] line.
def read_games(lines):
    game_line = []
# yields each game as a single string
    for line in lines:
        if line.startswith('[Event "') and game_line:
            yield "".join(game_line)
            game_line = []
        game_line.append(line)
# yields last game line because there is not event line after it
    if game_line:
        yield "".join(game_line)

# converts the PGN headers into a Python dictionary
def read_headers(pgn):
    headers = {}
#.strip removes spaces at the start and end, .splitline splits between enters ("\n")
    for line in pgn.strip().splitlines():
# ifnot line.strip() means that if the line is empty we stop. this seperates the headers from the game moves
        if not line.strip():
            break
# line[1:-1] removes the first and last character of the line, which is [] 
# .split(" ", 1) splits each header after the first word. 
        key, value = line[1:-1].split(" ", 1)
#  stores the value in the dictionary headers without the quotation marks due to value[1:-1]
        headers[key] = value[1:-1]  
    return headers


# 3. Decide which games are relevant
def usable_headers(headers):
# only 1+0, 5+0 and 10+0
    if headers.get("TimeControl") not in TIME_CONTROLS:
        return False
# only rated
    if not headers.get("Event", "").startswith("Rated "):
        return False
#only standard games, no variants or FENs
    if headers.get("Variant", "Standard") != "Standard" or "FEN" in headers:
        return False
# no identified bots
    if headers.get("WhiteTitle") == "BOT" or headers.get("BlackTitle") == "BOT":
        return False
# only completed games
    if headers.get("Result") not in ["1-0", "0-1", "1/2-1/2"]:
        return False
# only games from the month
    if not headers.get("UTCDate", "").startswith(MONTH.replace("-", ".")):
        return False
# return the gameid, e.g. https://lichess.org/Ab12Cd34/ -> Ab12Cd34
    game_id = headers.get("Site", "").rstrip("/").split("/")[-1]
# gameid needs to be 8 char and alphanumeric
    if len(game_id) != 8 or not game_id.isalnum():
        return False
# only games with valid Elo ratings, if the header cannot be converted to int or is missing, the game is rejected
    try:
        return int(headers["WhiteElo"]) > 0 and int(headers["BlackElo"]) > 0
    except (KeyError, ValueError):
        return False


# 4. Keep a random sample while reading the archive
def sample_games(lines):
    rng = random.Random(SEED)
# Each time control has its own empty list for storing games
    samples = {control: [] for control in TIME_CONTROLS}
# antoher dictionary that counts # eligable games for each time control
    eligible_seen = {control: 0 for control in TIME_CONTROLS}
# counts total # examined
    scanned = 0
# we intially assume the script will reach the end of the archive
    reached_end = True
# records time in seconds so we can calc how long processing takes
    started = time.time()

    for pgn in read_games(lines):
        scanned += 1
        headers = read_headers(pgn)
        if usable_headers(headers):
# increases individual counters for time controls
            control = headers["TimeControl"]
            eligible_seen[control] += 1
            pool = samples[control]
# fill sample pool if it is not full yet
            if len(pool) < POOL_SIZE:
                pool.append(pgn)
# if full, randomly replace games
            else:
                # For the nth eligible game, choose a number from 0 to n-1.
                # Replace a saved game only if that number is inside the pool.
                # This gives every eligible game the same chance of being kept int this iteraton.
                position = rng.randrange(eligible_seen[control])
                if position < POOL_SIZE:
                    pool[position] = pgn
# returns progress after 10k scans
        if scanned % 10_000 == 0:
            print(f"Read {scanned:,} games in {time.time() - started:.0f}s; eligible: {eligible_seen}", flush=True)
# stops scanning if the max number of games is reached, reached_end is now false because we stopped after MAX_GAMES
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
