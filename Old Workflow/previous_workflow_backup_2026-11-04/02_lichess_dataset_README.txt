Lichess collection: 1+0, 5+0 and 10+0
===================================

Keep the original 90k outputs in data/lichess_2026-10_balanced/.
Those outputs contain 30k per control, but all are from October 1.
Do not use them as a random sample spanning October.

Setup and small pilot
---------------------
From this folder:
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python 02_lichess_stratified_sample.py

Defaults: October 2026, seed 2026, 10 games per control, scan at most
20,000 archive records. This downloads only a small archive prefix.
It is deliberately labelled pilot_or_incomplete, even when quotas fill.
Output defaults to data/lichess_2026-10_pilot_v2/.
Use a NEW --output directory for each run; existing output is never erased.

Validate an output independently:
  .venv/bin/python 02_lichess_stratified_sample.py --validate-only --output data/lichess_2026-10_pilot_v2

The notebook is a short launcher and inspector for this same script.
Select the project .venv kernel. Its RUN_COLLECTION flag defaults to False
so opening/running the notebook does not start another collection.

Whole-month collection: only after lecturer approval
----------------------------------------------------
A whole-month probability sample requires reading the entire monthly archive.
There is no documented shortcut using arbitrary byte offsets in the .zst.
The October archive is 30,982,323,881 compressed bytes (~31 GB), containing
95,395,628 games. Budget hours, depending on CPU/network; pilot speed is not
a reliable full-run estimate because the heap, parsing and disk costs change.
No full-month run was started during this update.

Recommended: download once, with resumable download into a .part file:
  curl -fL --retry 5 -C - -o lichess_db_standard_rated_2026-10.pgn.zst.part https://database.lichess.org/standard/lichess_db_standard_rated_2026-10.pgn.zst

On success, rename .part to .pgn.zst; leave .part in place after an interruption
and rerun the same download command. Verify against the official checksum:
  sha256sum lichess_db_standard_rated_2026-10.pgn.zst
Expected October 2026 SHA256:
  043906ebfade1bfeb7c00087590fac505370936c028525e4722e2dbd4986ae86
Official checksum list: https://database.lichess.org/standard/sha256sums.txt
The collector fetches that list and checks the compressed checksum itself too.

Then run:
  .venv/bin/python 02_lichess_stratified_sample.py --local lichess_db_standard_rated_2026-10.pgn.zst --quota 30000 --max-games 0 --output data/lichess_2026-10_whole_month

Alternative (saves ~31 GB disk space but cannot resume a failed stream):
  .venv/bin/python 02_lichess_stratified_sample.py --quota 30000 --max-games 0 --output data/lichess_2026-10_whole_month

Both scan the full month. Neither creates the huge decompressed archive.
Allow about 1 GB extra for selected PGNs, SQLite and CSV, beyond the optional
compressed archive. Only priority/ID heaps (90k entries) and one game tree
are retained in Python memory. SQLite uses bounded caches. The .sqlite file
can be removed AFTER successful export and independent validation; retain
PGNs, CSV, manifest and validation report.

Sampling and filters
--------------------
Each game gets SHA256(seed|month|game_id), treated as a pseudorandom priority.
Keep the 30k lowest valid priorities separately in each time-control stratum.
This is a reproducible, order-independent hash-priority sample, not a claim
that SHA256 is a true random generator. Do not stop when the quotas first fill.
Retained PGNs live in SQLite, not a large Python list. A prospective candidate
is fully parsed only if it can improve the current sample; invalid candidates
never fill a slot. Larger priorities can safely be skipped after slots fill.
The header-candidate counts are NOT counts of all fully validated eligible games.

Require: rated Standard from the normal start, matching month/valid UTC date,
positive numeric ratings for both players, valid 8-character game ID, no BOT,
finished matching header/movetext result, legal moves, at least two plies,
and exactly one valid nonnegative clock annotation on EVERY mainline move.
Short games and resignations are allowed. A terminal board is not required.
Official single-mainline export syntax is expected; unknown/extra movetext
and variants/custom starts are rejected. No arbitrary 20-ply threshold.
These quality filters change the population to complete annotated games.

Retain and flag clock increases and suspected reduced starting clocks.
Neither a low first clock nor half-time is proof of berserk. Those heuristics
are for later sensitivity checks, not reliable labels. Nominal time control
is retained. Glicko2 ratings are commonly called Elo; rating pools differ
across Bullet, Blitz and Rapid.

Outputs and failures
--------------------
games_1m.pgn / games_5m.pgn / games_10m.pgn preserve original PGN text (UTF-8,
normalized record separation/newlines). Comments, existing evals, ratings,
player IDs, UTC date/time, opening, termination and other tags remain intact.
Do not use existing eval comments as predictors or inconsistent target labels.
games_metadata.csv records game IDs, ratings, players, dates, time controls,
plies, clock flags, source record number, hash priority and PGN record index.
dataset_manifest.json records settings, source checksum, versions, script
checksum, counts, selected-date coverage, counters, timings and output hashes.
validation_report.json is created by --validate-only, which replays all PGNs
and checks CSV fields, IDs, hashes and counts. Sampling_state.sqlite is the
intermediate selected-game store, not a resumable archive-scan checkpoint.

Progress reports scanned records, retained counts, rate and bytes about every
10 seconds, even when no game is accepted. Failed/interrupted runs keep a
failed manifest and SQLite diagnostics, with no successful completion claim.
Initial HTTP requests retry transient errors; a broken midstream read fails.
Use a new output directory to restart from the beginning. Local resumable
archive downloading is the simple recovery strategy. No silent overwrite.

The complete flag requires EOF, trusted compressed SHA256 match and all quotas.
A capped run remains a pilot even if quotas are full. Local plain PGN input
is supported for testing, but cannot claim verified monthly-archive completion.
Archive checksum verifies the input bytes; it does not establish Kaggle absence
or certify lecturer approval. Offline tests use their own fixture checksums.

Before move features and later Stockfish work
--------------------------------------------
PGN node.clock() is time AFTER the current move. For a pre-move feature, use
that player's previous recorded clock (usually two plies earlier). Do not use
the current move's clock or think time. For the first own move, nominal initial
time is unsafe if berserk/reduced time is uncertain: mark unknown or exclude
those first moves. Clock corrections/gifts can also make reconstruction imperfect.

Do not use final result, termination, future moves, post-move clocks, current
move SAN, or post-move engine scores as predictive inputs. Preserve them raw
for bookkeeping/labels only. Save train/validation/test game IDs before any
move-level split; all moves of a game must stay together. Players can recur
across games, so discuss this deployment assumption and consider a player/time
holdout sensitivity check later. A balanced time-control sample is not the
natural Lichess population mix.

Stockfish is not installed here and no engine-cost claim has been measured.
Before labeling, benchmark e.g. 100 sampled pre-move positions with a fixed
engine version, Threads=1, fixed Hash, fixed nodes/depth and MultiPV policy.
Compare best-vs-played values from the SAME side-to-move perspective and budget;
use an explicit separate mate policy and recheck labels near the 150cp boundary.
Reset engine hash consistently. Extrapolate measured seconds/position to a
manageable subset; don't automatically evaluate every move in 90k games.
No models are trained by this collection pipeline.

Checks and evidence
-------------------
Run offline regression checks:
  .venv/bin/python -m unittest -v test_sampling.py
See collection_review.md for source links, verified live-pilot results,
Kaggle uncertainty and course requirements. See existing_data_audit.json for
the read-only audit of the old 90k outputs.
