Complexity.py processes ALL games and ALL played moves with local Stockfish.
No sampling, cleaning or train/validation/test splitting happens here.

Run from the project folder:
.venv/bin/python "Python Scripts/Complexity.py"

Settings are at the top. OUTPUT_DIR must name a NEW folder.
Defaults: data/position_dataset, 100,000 nodes/search, 1 thread, 128 MiB, MultiPV 1.
Output: games_1m.csv, games_5m.csv, games_10m.csv and engine_protocol.json.

Groups are ordered: moves, board, game, clocks, move number, then evaluations.
Each group has individual functions, a function list, then its collector.
get_all_features joins the first five collectors; pre_eval_cp is added later.
Lists hold functions; their names generate the CSV columns, including GAME_COLUMNS.
The evaluation collector reads values calculated once in the main loop.

Stockfish starts once. Each move gets a free search and an actual-move-only search.
best_cp and played_cp are extracted once; move_target uses the extracted values.
There are 60 predictors, including pre_eval_cp, and 84 total CSV columns.
Actual/best moves, depth, nodes, mate information and statuses are kept for checks.
Use PREDICTOR_COLUMNS for X; played-move information and labels stay out of X.

Ordinary loss >200cp gives y=1; exactly 200cp gives y=0.
Missed winning mates and newly allowed losing mates also give y=1.
Mate-distance changes alone are ignored. Missing/bounded or inconsistent mate
results remain unclassified. Blank labels are not zero.
Clock features use earlier annotations only. Suspicious values remain for cleaning.
The full README.md explains the workflow, features and labeling rules.
