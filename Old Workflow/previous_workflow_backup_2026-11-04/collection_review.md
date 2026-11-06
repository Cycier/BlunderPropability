# Collection review — 4 November 2026

The original collector's early-stop mode produced 90,000 unique game IDs,
30,000 per control, all dated 1 October. Those files are preserved. The
replacement defaults to a bounded pilot; a complete monthly sample requires
reading the full source and checking its compressed SHA256.

## Verified source and selection

The [official archive](https://database.lichess.org/standard/) lists October
2026 at 30,982,323,881 bytes and 95,395,628 games. It is UTF-8 PGN in Zstandard.
The [official notes](https://database.lichess.org/#standard_games) document
clock annotations since April 2017, BOT title tags and Glicko2 ratings.
The [exporter](https://raw.githubusercontent.com/lichess-org/database/master/src/main/scala/Games.scala)
filters rated games by creation date and orders them chronologically.
Stopping once quotas fill therefore samples an early-month prefix.

The replacement assigns seeded hash priorities and retains the lowest valid
priorities per control. It streams either a remote archive or a local compressed
file, stores PGNs in SQLite and keeps only bounded heaps of keys in memory.
Candidate games are validated before entering the sample. A smaller hash from
later in the month can replace an earlier game. No second full archive pass
is required. Output order is by priority rather than game date.

The [official checksum list](https://database.lichess.org/standard/sha256sums.txt)
is checked for full runs; reaching decompressor EOF alone is insufficient to
prove an untruncated input. Midstream failures are reported, not silently retried.
A resumably downloaded local archive is the simplest full-run recovery option.

## Course constraints and Kaggle check

The supplied course PDF requires a predictive question, lecturer approval before
starting the project, a dataset not also on Kaggle, explainable methods and code,
a fixed-seed reproducible submission, and an AI-use statement. Register by
11 November; submission is due 30 November 2026 at 23:59 (Zurich time).
The PDF specifies a 3–6-page report and slides, code and data/shared data link.
The present work is a bounded data-feasibility check; approval is unverified.

Searches for the exact October filename, October 2026 Lichess games, and monthly
standard-rated dumps found no verified exact October archive on Kaggle. This is
not proof of absence. [Kaggle already hosts Lichess-derived datasets](https://www.kaggle.com/datasnaek/chess/tasks),
including a different 20,058-game API sample. The course restriction concerns
the dataset, not merely the website used to download it. Do not claim that
resampling or downloading directly guarantees compliance. Disclose the common
source and request an explicit ruling on the proposed October source/sample.

The [existing similar project](https://github.com/pm4o/Skill-Aware-Chess-Mistakes-Prediction)
already combines position, skill and time pressure. Its README describes March
2026 data, 305k positions, depth-18 MultiPV-5 Stockfish labeling and CatBoost.
Controlled 1/5/10-minute comparisons, explicit complexity features and the later
exploitation question are proposed distinctions; originality has not been
established by a code-level or literature review. Subdirectory browsing was
not available during this review.

## Leakage and future scope

[python-chess documents node.clock() as the time after the move](https://python-chess.readthedocs.io/en/latest/pgn.html#chess.pgn.GameNode.clock).
Use the same player's previous clock for a pre-move feature. The first move,
berserk and clock corrections need explicit missing-value/quality handling.
Do not use the current move clock, final result, termination or engine eval
comments as predictors. Raw PGNs retain these fields for later bookkeeping.

Game-level train/validation/test splitting remains the next modeling protocol;
no moves, labels or models have been produced. Blunder exploitation is deferred.
Stockfish was not found locally, so engine throughput and the 150cp labeling
protocol remain unbenchmarked. Benchmark a fixed engine/search protocol on a
small position set before choosing the label volume. Parsing throughput is
not an estimate of engine throughput.

## Tests actually performed

- Ten offline regression tests pass: exact hash selection, seed/reordered-input
  reproducibility, invalid-game exclusion, deduplication, legal moves/results,
  clocks/flags, no overwrite, incomplete pilots, truncated input, interrupted
  HTTP reads and semantic CSV cross-checking.
- A live 20,000-record pilot retained 10 games per control (30 total), reading
  6,684,825 compressed bytes in 4.677 seconds. Independent PGN/CSV replay passed
  with zero issues. Its manifest correctly says pilot_or_incomplete.
- A second live pilot scanned 100,000 records and retained 100 games per control
  (300 total), reading 32,768,750 compressed bytes in 50.531 seconds.
  Independent replay passed with zero issues in 7.438 seconds.
- Original-data audit: all 90k IDs/headers/CSV fields checked; five unfinished
  games found. A seeded sample of 300 games passed full replay (20,431 plies).
  All-90k move-level legality was not checked.
- The notebook uses the same script and a disabled-by-default collection switch.
  Output validation is separate from the sampling pass.

Live timings are specific to this machine/network. The 90k heap, SQLite work,
full-source download, disk caching and candidate mix change scaling. Do not
extrapolate a reliable whole-month runtime from the tiny pilot. The full archive,
90k whole-month export, full-archive checksum match and Stockfish cost have not
been tested. See the manifests and validation reports for machine-readable
measurements, and existing_data_audit.json for the scope of the original-data audit.
