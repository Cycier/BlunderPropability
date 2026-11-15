StockfishComplexity.py now uses YOUR LOCAL STOCKFISH, not saved PGN evaluations.

Run it with VS Code's Run Python File button, or from the project folder:
.venv/bin/python "Python Scripts/StockfishComplexity.py"

Defaults: 10 random games per file, 2 positions per game (about 60 rows).
Search: Stockfish 19, 100,000 nodes/search, 1 thread, 128 MiB, MultiPV 1.
Edit STOCKFISH_PATH and the sampling/search settings at the top of the script.
For about 6,000 rows, set GAMES_PER_FILE = 1000 after checking a small run.

A fresh data/stockfish_positions_TIMESTAMP/ folder is created every run.
For initial classification, filter label_status == "finite_cp".
Use predictor_columns.txt for X; keep chosen-move and label columns out of X.
No Wi-Fi needed; your computer must stay on and awake.

The root README.md explains the engine protocol, labels, clocks and all 60 features.
