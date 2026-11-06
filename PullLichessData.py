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
MAX_GAMES = 1000000           # 10m took 20 Minutes, limit to 1 million, we only pick 90k here anyways
# Makes random sampling reproducible between runs.
SEED = 2026
# Sets the folder where output files will be saved.
OUTPUT_DIR = Path("data/results")
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


# 5. Check legal moves and clock values and that result matches.
def check_game(pgn):
# uses chees.pgn to read the game from the PGN string
    game = chess.pgn.read_game(io.StringIO(pgn))
# throw unreadable or illegal games
    if game is None or game.errors:
        return None
#check if result in the PGN matches (last entry is 1-0 or 0-1 or 1/2-1/2) result in the headers, if not throw
    if pgn.strip().split()[-1] != game.headers.get("Result"):
        return None
# counts # moves
    moves = 0
# for each node (move) in the mainline, check that the clock exists and is not negatvie
    for node in game.mainline():
        clock = node.clock()
        if clock is None or clock < 0:
            return None
        moves += 1
# rejects games with fewer than 2 moves and cases where the number of moves in not equal to # [%clk ...] comments in the PGN
    if moves < 2 or pgn.count("[%clk ") != moves:
        return None
# outcome is the final node, .board reconstructes and python chess checks if the final position has a recognizable chess outcome, resignations would lead to outcome returning none
    outcome = game.end().board().outcome()
# checks if outcome disagress with result in pgn header, so resignations are kept but invalid none results are thrown
    if outcome is not None and outcome.result() != game.headers["Result"]:
        return None
# if all checks pass, we get the number of moves back, otherwise we get none
    return moves


# 6. Save PGNs and one CSV row per game
def save_games(samples):
    rng = random.Random(SEED)
    counts = {control: 0 for control in TIME_CONTROLS}
    rejected = {control: 0 for control in TIME_CONTROLS}
# creates a set for all saved ids
    saved_ids = set()
# defines csv columns, please is total individual moves so 1. e4 1. e5 is 2 plies or 1 full move
    fields = ["game_id", "utc_date", "utc_time", "white", "black", "white_elo", "black_elo", "time_control", "result", "termination", "plies", "pgn_file"]
# opens csv, w opens for writing and overwriting, newline prevents extra blank lines, encoding is utf , opens the csv as a csv
    with (OUTPUT_DIR / "games_metadata.csv").open("w", newline="", encoding="utf-8") as csv_file:
# csv.dictwriter lets us write csv rows from dictionaries, writer.writeheader writes the first row containing column names
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
# loops through the three time controls, shuffles the pool of games
        for control, label in TIME_CONTROLS.items():
            pool = samples[control]
            rng.shuffle(pool)
# fstring creates the filename using the current label (time control)
            filename = f"games_{label}.pgn"
# open the file
            with (OUTPUT_DIR / filename).open("w", encoding="utf-8") as pgn_file:
                for pgn in pool:
# stop when we have enough games
                    if counts[control] == GAMES_PER_CONTROL:
                        break
# extract headers from function, gameid from URL and moves from function, reject invalid/duplicate games and increase counter
                    headers = read_headers(pgn)
                    game_id = headers["Site"].rstrip("/").split("/")[-1]
                    moves = check_game(pgn)
                    if moves is None or game_id in saved_ids:
                        rejected[control] += 1
                        continue
# save accepted pgn and add two newlines after game which means there is one empty line between games
                    pgn_file.write(pgn.strip() + "\n\n")
# function that takes a dictionary and writes the values into the corresponding csv columns
                    writer.writerow({
                        "game_id": game_id, "utc_date": headers["UTCDate"],
                        "utc_time": headers.get("UTCTime", ""),
                        "white": headers.get("White", ""), "black": headers.get("Black", ""),
                        "white_elo": headers["WhiteElo"], "black_elo": headers["BlackElo"],
                        "time_control": control, "result": headers["Result"],
                        "termination": headers.get("Termination", ""),
                        "plies": moves, "pgn_file": filename,
                    })
# add games to the set of saved ids, increase counter
                    saved_ids.add(game_id)
                    counts[control] += 1
# After loop is done, print the # of saved games for each time-control game
            print(f"Saved {counts[control]:,} games for {control}")
# return the two dictionaries as a tuple
    return counts, rejected


# 7. Open the compressed archive and run the steps above
def run():
    # A new folder prevents accidentally overwriting an earlier dataset.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
# stores data about the data collection process
    summary = {"status": "started", "source": SOURCE_URL, "month": MONTH,
               "seed": SEED, "games_per_control": GAMES_PER_CONTROL,
               "pool_size": POOL_SIZE, "max_games": MAX_GAMES,
               "source_checksum_checked_by_script": False,
               "local_archive": str(LOCAL_ARCHIVE) if LOCAL_ARCHIVE else None}
# response holds http respon from the server, source will hold the data stream
    response = None
    source = None
# try to execute code that may raise an error e.g. failed download, expect and finally handle this exception
    try:
# if a local archive doesnt exist, we download
        if LOCAL_ARCHIVE is None:
# source url is the archive url, stream downloads progessively instead of everything at once, max timeout is 30s for connection and 120 for incoming data, accept-encoding identity means we want the raw data, not compressed
            response = requests.get(SOURCE_URL, stream=True, timeout=(30, 120),
                                    headers={"Accept-Encoding": "identity"})
# checks whether the http request failed
            response.raise_for_status()
            source = response.raw
# otherwise we use the local archive r=read, b=binary mode. important because because .zst contains binary data and we dont want python to try to decode it as text
        else:
            source = LOCAL_ARCHIVE.open("rb")
# decompresses: zstandard.ZstdDecompressor() creates a decompressor object, .stream_reader(source) creates a stream reader that reads from the source and decompresses it on the fly
# read_across_frames=True allows reading continuously across multiple compressed frames if the archive contains them.
        with zstandard.ZstdDecompressor().stream_reader(source, read_across_frames=True) as reader:
# convert bytes into strings using UTF-8 encoding; .zst->bytes->readable pgn text (with compressor and then IO wrapper)
            with io.TextIOWrapper(reader, encoding="utf-8") as text:
# samples games
                samples, eligible, scanned, reached_end = sample_games(text)
                # A full remote read must match the server's advertised size.
                if reached_end and response is not None:
                    expected_size = response.headers.get("Content-Length")
                    if expected_size and source.tell() != int(expected_size):
                        raise ValueError("Download ended early. Run again in a new output folder.")
# other function called from step 6 to check the sampled games, returns samples and their totals numbers in the previously defined dictionaries
        counts, rejected = save_games(samples)
# check if target was reached for each time control, else print a message
        enough_games = all(count == GAMES_PER_CONTROL for count in counts.values())
# for bookeeping check collection status
        status = "whole_source_sample" if reached_end and enough_games else "pilot_or_incomplete"
# update previously defined summary dictionary with results of run
        summary.update(status=status, games_scanned=scanned, eligible_seen=eligible,
                       reached_end=reached_end, saved=counts, rejected_in_sample=rejected)
        if not enough_games:
            print("Not enough valid games. Increase the pool size or pilot scan limit and rerun.")
# handle errors: most ordinary exceptions and manual interruption (cntrl+c)
    except (Exception, KeyboardInterrupt) as error:
        summary.update(status="failed", error=str(error))
        raise
# always executed when executions leaves the try/except block, regardless of result, closes source and http response if exist
    finally:
        if source is not None:
            source.close()
        if response is not None:
            response.close()
# converts the dictionary of the summary into a json
        (OUTPUT_DIR / "collection_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Finished: {summary['status']}. Files are in {OUTPUT_DIR}")
    return summary

# execute the script if it is run as the main program, not when imported as a module
if __name__ == "__main__":
    run()
