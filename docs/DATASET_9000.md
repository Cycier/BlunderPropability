# Final dataset record — 9,000 games

This record supersedes the earlier 825-game run plan as the description of the completed dataset. It records the delivered files and the subsequently recovered home-PC exporter and checkpoint runner.

## Inputs and counts

Authoritative shared raw inputs are `data/MAIN/games_1m.csv`, `games_5m.csv` and `games_10m.csv`.

| Control | Games | Raw positions | Valid labels | Blank labels | Blunders | Rate among valid labels |
|---|---:|---:|---:|---:|---:|---:|
| 1+0 | 3,000 | 194,221 | 194,191 | 30 | 23,113 | 11.90% |
| 5+0 | 3,000 | 202,576 | 202,549 | 27 | 22,507 | 11.11% |
| 10+0 | 3,000 | 190,030 | 190,007 | 23 | 21,826 | 11.49% |
| Total | 9,000 | 586,827 | 586,747 | 80 | 67,446 | 11.5% |

All blanks have `label_status=inconsistent_mate_evaluations`. Every selected game's full played-ply sequence is present. The exact selected game IDs, source files and ply counts are in `data/MAIN/provenance/verification.json` (`complete_games`).

The original pool is 90,000 rated standard games, 30,000 per control, with 5,893,244 played positions. The original PGNs/metadata remain in `data/results/`. Dates span 1 October 2026, 00:00:02–10:45:57 UTC. This is an early-archive prefix, not a whole-month sample.

## Selection and processing history

The initial 825-game selection used seed 20261118, 275 per control. The delivered 9,000-game membership includes all those games and excludes the 30 pilot games; this was checked during consolidation. The prepared manifest hash matches the producing run manifest.

The transferred context reports extension to 3,000 per control by seeded shuffling of remaining eligible games using 2026111801 plus the control index, with a rotating control queue. The manifest records seed 2026111801, 12 independent workers and a 3,000-game-per-control cap. The queue/checkpoint source was subsequently supplied. Its `make_plan(3000)` was checked against the records and reproduces all 9,000 IDs, ply counts and per-control order exactly, without running Stockfish or cleaning.

The context reports interruption/recovery and subsequent checkpoint-based continuation. The supplied continued-run manifest starts at **18 Nov 2026 14:11:55 Europe/Zurich**; its verification record finishes at **19:43:50**. Those timestamps do not measure the entire dataset's computation because earlier checkpoints were reused. See the preserved context for the reported history; instructions in that text were not executed during consolidation.

## Engine and labels

The supplied protocol records Stockfish 19, 100,000 nodes/search, one thread and 128 MiB hash **per worker**, MultiPV 1, tablebases disabled and fresh search state. Twelve workers means independent single-thread engines, not one engine with Threads=12. Full board history is retained.

Best and played continuations use the same pre-move board and mover perspective; the best result is reused when its PV move was played, otherwise the actual move is forced at the root. The latest unbounded score/PV is used and depth/total nodes are recorded. These are finite-search estimates, not exact chess values.

For two finite scores, `eval_loss_cp = best_cp - played_cp`, and `y = int(eval_loss_cp > 200)`. Exactly 200 is zero. Negative losses remain recorded. Mates are not converted into fabricated centipawn values:

| Best continuation | Played continuation | y |
|---|---|---:|
| Winning mate | Finite or losing mate | 1 |
| Finite | Losing mate | 1 |
| Winning mate | Winning mate | 0 |
| Losing mate | Losing mate | 0 |
| Finite | Winning mate | 0 |
| Losing mate | Finite or winning mate | blank |
| Missing/bounded result | Any | blank |

Mate-distance changes are ignored. The final delivery contains 80 contradictory losing-mate rows; no other blank-label reasons were found. Earlier pilot budget checks demonstrated possible label changes at larger search budgets. No engine accuracy guarantee follows from the file/arithmetic checks.

## Schema and leakage

Raw order: `y` + 60 candidate predictors + one column named a single space + 24 metadata/audit columns = 86 columns. The protocol provides the explicit predictor whitelist. Feature groups contain 7 move, 40 board, 4 game, 7 clock and 1 move-number measurements, plus pre-move `pre_eval_cp`. See [FEATURE_DICTIONARY.md](FEATURE_DICTIONARY.md).

`pre_eval_cp` is a pre-move advantage measurement, separate from elementary complexity proxies. Best–second-best gaps and acceptable-alternative counts are absent. Actual moves, played evaluations, score losses, mate/status diagnostics and engine best moves remain metadata and must not enter X.

Rows describe the board before the actual move. Pre-turn clocks use earlier own annotations; first own clocks are missing. Raw anomalies remain for independent cleaning. Metadata/labels must not be used to backfill predictive features from future information.

## Verification performed on the original PC

The read-only consolidation audit checked all 586,827 rows for exact protocol/schema, unique game/ply keys, contiguous ply sequences, time controls/source/player metadata and finite-label arithmetic. Counts and all 9,000 game IDs/ply counts match the transferred verification report and original 90,000-game metadata. All four source PGN/metadata hashes match the run manifest. The supplied engine's binary hash also matches. The engine protocol JSON equals the protocol embedded in the manifest.

No Stockfish rerun, cleaning, splitting or model fitting was performed during this consolidation. Validation results are in `data/MAIN/provenance/consolidation_validation.json`; raw CSV SHA256 values and copy verification are preserved alongside the original records.

## Recovered run source and available files

The initial transfer contained the original `Complexity.py` (SHA256 `703a3617547a5df44ceefbbdfec96189ed2d88e1c706c842a98c4b9b9aaa469e`). The user subsequently supplied the home-PC exporter and checkpoint runner. The pasted exporter lacks only its final newline: appending one LF gives SHA256 `92b694492588d37742441cb76c78062a1e2f34aadf92dae16b34ce159655bcc1`, exactly matching the run manifest. This recovered file is retained as `data/MAIN/provenance/home_pc_source/Complexity.py`; no source-code approximation was made.

All shared feature, clock, evaluation, target and `process_pgn()` definitions are unchanged. New code changes the Stockfish transport to an asynchronous connection and adds startup/path/protocol handling. The original active main script is preserved. The runner is archived as `RunOvernight.py` (assigned filename), with the unchanged reference cleaner beside it. Its hash was not recorded in the original manifest, so its association is supported by the user's identification and exact selection reproduction, not an original runner fingerprint.

The runner handles workers/checkpoints/resumption on relaunch and final verification/cleaning; it does not inhibit OS sleep or provide a separate watchdog service. External launch/power-management configuration remains unavailable. Its 3,000-per-control cap comes from the existing run manifest; a fresh default invocation does not recreate that cap. See the source archive README and `source_recovery.json`.

The preserved Stockfish distribution has executable SHA256 `0f83d24cc46d2c66c60f16001af5444873bc112b7d028594513426894c12da19`, matching the manifest. Licenses, source and bundled documentation are retained under `stockfish/`.

Final cleaned CSVs and their cleaning report were not transferred. The context reports 586,747 reference-cleaner rows across all 9,000 games; this matches the valid-label count, but the cleaner was not rerun here. `CleanData.py` is unchanged and can serve as a reference for teammates' independent cleaning.
