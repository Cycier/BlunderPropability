# Pilot and data audit — 17 November 2026

The current position exporter was tested without changing its feature/label code. This hash identifies the tested source before the two production input/output settings were changed. Pilot source SHA256: `703a3617547a5df44ceefbbdfec96189ed2d88e1c706c842a98c4b9b9aaa469e`.

## Source inventory

90,000 games, exactly 5,893,244 played plies: 1,940,640 at 1+0; 2,028,151 at 5+0; 1,924,453 at 10+0. The full parser audit found zero parse errors, duplicate IDs, rating problems or time-control problems. All move clock annotations are present. All games are from 1 October 2026, 00:00:02–10:45:57 UTC; this is not a month-wide sample. 975 games have clock increases or above-nominal clocks. The 180,000 first own moves have no prior own clock annotation.

## Reproducible selection and protocol

Seed 20261117 selects 10 game indices per complete available time-control file without using labels or source evaluations. The small pilot takes one of those games per control. `pilot_selection.json` records IDs/indices. Every played move of each selected game is processed, preserving clocks and board history.

Stockfish 19, 100,000 nodes/search, Threads=1, Hash=128 MiB, MultiPV=1, no tablebases. Fresh search state is used for each search. Best and played-root scores use the same pre-move board and mover perspective. The best result is reused when it matches the actual move. The 30-game pilot needed 2,518 engine searches, not two for every position.

## Results

Small pilot: 3 games, 128 positions, 17 blunders; 78.9 seconds. Larger pilot:

| Control | Pilot games | Positions / valid labels | Blunders | Rate |
|---|---:|---:|---:|---:|
| 1+0 | 10 | 600 / 600 | 78 | 13.00% |
| 5+0 | 10 | 525 / 525 | 52 | 9.90% |
| 10+0 | 10 | 425 / 425 | 55 | 12.94% |
| Total | 30 | 1550 / 1550 | 185 | 11.94% |

The 30-game pilot took 923.6 seconds (15.39 minutes). Extrapolating by positions gives about 40.6 days for the full pool on one engine process; this is an estimate, not a guarantee.

All 1,550 rows passed source checks for FEN, moves, 47 board/move measurements, ratings, pre-turn clocks, schema and metadata, plus arithmetic and label-rule consistency checks. These checks do not establish engine-label accuracy. No rows were unclassified in this pilot. Of 185 positives, 28 use mate rules (16 newly allowed losses, 12 missed wins); 157 use finite cp loss. There are 55 mate comparisons overall. Thirty-nine rows have a valid y and missing pre_eval_cp and are retained by cleaning. The cleaner kept all 1,550 pilot rows; synthetic tests cover errors, duplicates, missing labels and clock anomalies not present in these pilot games.

Pilot blunder rates are descriptive for 30 sampled games, not a precise population estimate. Positions within games are dependent. No fitted model performance is claimed.

## Budget check and frozen cohort

We therefore fixed a seeded cohort of 825 games (275 per control), containing 54,262 positions. Its estimated run time is 9.0 hours, leaving headroom within 12 hours. The 30 pilot games are excluded.

Selection seed 20261118; all 825 selected PGNs were parsed again and their exact 54,262 positions verified against source metadata. The game count was fixed from pilot throughput and average source-game length before the production draw. No selection used labels or existing eval annotations. Inputs are raw PGN copies retaining moves, clocks, ratings, IDs and metadata. Estimated raw CSV size is 21.0 MB, plus a similar cleaned copy; actual size will vary.

## Label stability, not certified accuracy

Ten uniformly selected labeled pilot positions per control were checked at 500,000 nodes with otherwise identical settings and full move history. All 30 remained classifiable; 29 labels agreed. There were four source positives and five reference positives. The disagreement was smxWctGX, ply 83 (1+0): estimated loss -336cp at 100k nodes versus 7,700cp at 500k nodes, both from an already losing position. These are finite-search estimates; the comparison does not establish 96.7% label accuracy. Source labels were not selectively changed. See `label_stability.csv` and its summary.

## Tests and remaining decisions

16 tests pass for the actual final collector, including forced mates, both mate-zero representations, bounded/missing scores, best-result reuse, clock timing, and PGN-error row/continue behavior. Ten cleaner tests pass. Strict TimeControl parsing is retained because all 90,000 actual headers were verified. Missing pre_eval_cp remains missing, with an explicit pre-move missing-value indicator for the engine-feature model. Imputation/encoding/scaling are fitted inside training folds later.

The course's no-Kaggle eligibility interpretation still requires explicit clarification; topic approval does not prove this condition. No training/test split or model has been fitted yet. The production engine run has not been started.
