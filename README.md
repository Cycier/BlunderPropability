LIGHTWEIGHT POSITION DATASET
============================

Run from the project folder, or use VS Code's Run Python File button:
  .venv/bin/python "Python Scripts/StockfishComplexity.py"

Edit the settings at the top. The default analyzes the first ONE game from each
PGN, every played move, at depth8. This is a pilot, not a final random sample.
GAMES_PER_FILE = None would process everything; do not start with that setting.
Depth8 still needs stronger-search validation before final modeling.
A fresh timestamped output folder preserves earlier results on every run.

Outputs
---------
positions.csv: ONE row per played move (one player's turn, also called a ply).
run_info.txt: engine version, settings, completion status and runtime.
There is no new move_evaluations.csv. Older output folders remain unchanged.

Legal-move scores are needed for the calculations, but not as a saved table.
The script evaluates all legal choices, calculates the counts and the label,
then continues to the next position. It writes rows as it goes; it does not
accumulate the entire dataset in memory.

Column meanings
-----------------
Identifiers: game_id, ply, FEN.
Predictors: white_elo, black_elo, player_to_move, time_control, initial_seconds,
  time_left_seconds, legal_moves, captures, checks, in_check, material_balance_cp,
  best_score_cp, good_move_count, bad_move_count, best_second_gap_cp.
Quality information: clock_status and evaluation_status.
TARGET/AUDIT ONLY: played_move, played_score_cp, played_mate_in_moves, cp_loss, y.
Never use the target/audit columns as predictors.

The counts describe ALL legal moves, from the CURRENT player's perspective:
  good_move_count: number losing <=GOOD_MOVE_CP (default50), including the best.
  bad_move_count: number losing >BLUNDER_CP (default200).
  y: whether the ONE move actually played lost >BLUNDER_CP, not a move count.
Exactly 200 cp gives y=0 and does not add to bad_move_count.
Example: scores +100, +60, -150 give good_count2 and bad_count1. Playing -150
loses 250 cp, so y=1. Saving these three scores as separate rows is unnecessary.

Mate/bound/incomplete evaluations have blank cp measurements and labels, never
an automatic y=0. The conservative mate policy also flags a position if an
unplayed alternative has a mate score. With one legal move, good_move_count=1
and the best-second gap is blank. If its score is finite, bad_move_count=0 and y=0.

Clocks and score protocol
--------------------------
Time left estimates the START of the turn from the same player's PREVIOUS
annotation. First-move clocks, missing annotations and previously observed
clock anomalies remain missing. The current move's after-clock cannot affect
its own row. Unrecorded adjustments during the opponent's turn remain unknown.

Stockfish uses fixed depth, one thread, 128 MiB memory, full strength, no external
tablebases and fresh search state per position. Full board history is retained.
All choices use one all-legal MultiPV search, then the played move is looked up
separately for the label. Centipawn scores and mate distances are kept distinct.
Material values are pawn100, knight320, bishop330, rook500, queen900, from the
mover's perspective. These counting values differ from Stockfish's evaluation.

The engine calculation still dominates runtime: removing the detailed CSV saves
disk space, not the need to search legal moves. python-chess already handles PGN
parsing, board rules and the engine connection. Another wrapper library would
not remove that search work. It is the only third-party Python dependency here.

Checks and limits
-------------------
Run a pilot from the project folder with:
  .venv/bin/python -B "Python Scripts/StockfishComplexity.py"

The script requires a working Stockfish executable at STOCKFISH_PATH and the
PGN files listed in PGN_FILES. See run_info.txt in the timestamped output
folder for the engine version, settings, completion status and runtime.

In the earlier pilot, four of ten positions chosen CLOSEST to 200cp changed label
at depth10 versus depth8. This is a targeted stress check, not an overall error
rate. Search depth and label stability remain open questions.

Later split whole games into train/validation/test before fitting preprocessing.
The current 90k source covers part of 1 October, not the full month. Topic approval
is confirmed; the course's no-Kaggle eligibility rule remains unresolved.

Library documentation: https://python-chess.readthedocs.io/en/latest/engine.html
