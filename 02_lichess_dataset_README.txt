Lichess sampling — simple version
================================

Start with 02_lichess_stratified_sample.ipynb. It shows the actual Python code
in order, with explanations. The .py file contains the same collection code.

What Lichess stores
-------------------
A monthly archive is a text file of chess games in PGN format, compressed
as .pgn.zst. Each game has headers, then moves and comments. For example:

  [WhiteElo "1500"]
  [TimeControl "60+0"]

  1. e4 { [%clk 0:01:00] } e5 { [%clk 0:00:59] } ...

60+0 means 60 seconds initially and zero extra seconds per move.
300+0 is five minutes; 600+0 is ten minutes.
The clock next to a move is the clock AFTER that move.

Our approach
------------
1. Decompress and read one game at a time.
2. Check its headers: right time control, rated standard game, normal start,
   positive ratings, finished result, correct month, game ID and no bots.
3. Keep a random reserve separately for each time control.
4. Shuffle each reserve and check games with python-chess. Save the first
   requested number with legal moves and a clock on every move.
5. Write original PGNs, a CSV of game information, and a short JSON summary.

The reserve uses standard reservoir sampling. For example, to keep two games:
keep the first two. For game 3, draw a number from 0 to 2. If it is 0 or 1,
replace that saved game; otherwise discard game 3. For game 4, draw from 0 to 3,
and so on. Each eligible game has the same chance of ending up in the reserve.
A fixed seed makes the result repeatable for the same archive and settings.

We keep 20% extra because some sampled games may fail move/clock validation.
For a full run, this means a reserve of 36,000 per control, from which we save
30,000 valid games. If too few pass, the output is incomplete: increase the
reserve and rerun. Never fill missing places by taking games from the start.

This stores only the reserve, not the full archive. Based on the existing
PGNs, the full reserve is about 250 MB of raw text plus Python overhead.

Small test
----------
Dependencies are already installed in this project's .venv.
For a fresh environment: python -m pip install -r requirements.txt

In the notebook, use the project environment and follow the cells.
Or run from this folder:
  .venv/bin/python 02_lichess_stratified_sample.py

Settings are at the top of the script / first notebook code cell:
  GAMES_PER_CONTROL = 10
  MAX_GAMES = 20_000
  OUTPUT_DIR = Path("data/simple_pilot")

The saved small test is already in data/simple_pilot. Before collecting again,
choose a NEW output folder. Existing folders are never overwritten.
A test reading only 20,000 records is a prefix pilot, not a whole-month sample.

Full collection — after lecturer approval
----------------------------------------
Set GAMES_PER_CONTROL = 30_000, MAX_GAMES = None, and choose a new output folder.
Read the entire month, even after enough games have been seen. Lichess orders
the archive by date, so stopping early misses the rest of the month.

The script can stream from the official URL (LOCAL_ARCHIVE = None), or read an
already downloaded .pgn.zst by setting LOCAL_ARCHIVE to its Path. Do not unpack
the entire file. October 2026 is about 31 GB compressed. A full read can take
hours; it has not been run here. Interrupted remote reads restart from the
beginning. A local archive can be downloaded with resume support separately.

For a local full-month archive, first verify its SHA256 against the official
checksum list using your download tool or sha256sum. Checksum verification is
a separate step, not built into this simple script. Its whole_source_sample
status means it reached the end and met quotas; it does not certify the file
checksum or prove the file contains the complete official month. The parser
assumes the usual official PGN syntax; it is not a forensic corruption checker.

Sources:
  https://database.lichess.org/standard/
  https://database.lichess.org/standard/sha256sums.txt

Outputs and important limits
----------------------------
games_1m.pgn / games_5m.pgn / games_10m.pgn: original games and clock comments.
games_metadata.csv: IDs, players, ratings, date/time, control, result and plies.
collection_summary.json: settings, counts and whether the source ended.
If collection fails, the summary records failure. Use a new folder to retry.

We preserve complete short games (at least one move by each player). A game
can end by resignation; its final board does not have to be checkmate.
We assume the official archive has one record per game; duplicate saved IDs
are rejected. The script retains unusual clocks, such as berserk games or
time additions; handle these explicitly when making before-move features.

For later features, use the player's PREVIOUS recorded clock as the time before
a move. The current move's clock would leak information. First moves and
reduced starting clocks need special treatment later. Do not use game result
or termination as predictors. Split whole games before creating modeling rows.

Lecturer approval, Kaggle compliance and novelty remain unresolved; this
simplification does not change those findings. No model training or Stockfish
labeling is done here. Previous work and audit notes are preserved in
previous_workflow_backup_2026-11-04/, and the original 90k data is untouched.
