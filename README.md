# Chess blunder project — final 9,000-game dataset

**Dataset construction is complete.** Start with the three **raw, uncleaned CSVs in `data/MAIN/`**. They contain **9,000 games** (3,000 per control) and **586,827 positions**. Each row describes a position before one played move. Do not use older pilot outputs as the final dataset.

| Time control | Raw CSV | Games | Raw positions | Valid binary labels | Blunders |
|---|---|---:|---:|---:|---:|
| 1+0 | `data/MAIN/games_1m.csv` | 3,000 | 194,221 | 194,191 | 23,113 |
| 5+0 | `data/MAIN/games_5m.csv` | 3,000 | 202,576 | 202,549 | 22,507 |
| 10+0 | `data/MAIN/games_10m.csv` | 3,000 | 190,030 | 190,007 | 21,826 |
| **Total** | | **9,000** | **586,827** | **586,747** | **67,446** |

All 80 blank labels are inconsistent mate evaluations. Keep them unclassified. The blunder rate among valid labels is approximately **11.5%**.

## Start here

- [Team handoff](docs/TEAM_HANDOFF.md): which files to use and what remains.
- [Dataset record](docs/DATASET_9000.md): sampling, engine, target, validation and provenance limits.
- [Feature dictionary](docs/FEATURE_DICTIONARY.md): the 60 candidate predictors.
- [Documentation index](docs/README.md): current records versus historical plans.
- [Run evidence](data/MAIN/provenance/README.md): original manifest/protocol/verification and consolidation checks.

## Folder map

```text
data/MAIN/                  FINAL raw CSVs — shared cleaning inputs
  provenance/               Run records, exact game list, hashes and copy verification
data/results/               Original 90,000-game PGNs and source metadata
Python Scripts/             Existing scripts, including the reference cleaner
stockfish/                  Transferred engine distribution, matching manifest hash
docs/                       Handoff, dataset record, feature dictionary and old documents
data/pilot_20261117/         Historical pilot evidence
data/run_input_20261118/     Historical 825-game starting subset
data/<other folders>/       Earlier experiments; not final shared inputs
```

## Script roles

- `Python Scripts/PullLichessData.py`: original downloader; preserved.
- `Python Scripts/Complexity.py`: original readable feature/label implementation; preserved. Its defaults still point at all source PGNs, so do not rerun it merely to start analysis.
- `Python Scripts/CleanData.py`: reference cleaning approach; imports schema/clock helpers from `Complexity.py`. Its default input is an older planned folder; use explicit paths for `data/MAIN` (see team handoff).
- `Python Scripts/PrepareGames.py`: historical preparation of the initial 825-game subset.
- `Python Scripts/StockfishComplexity.py`: older implementation, retained for later cleanup.

No active Python scripts or earlier datasets were deleted or changed during consolidation. The home-PC exporter and checkpoint runner were subsequently supplied and are preserved in [`data/MAIN/provenance/home_pc_source/`](data/MAIN/provenance/home_pc_source/). Restoring the pasted exporter's single missing final newline gives an exact match to the run manifest hash. Its feature/clock/label/move-processing functions are unchanged from the original script. External sleep-inhibition or supervisor launch configuration was not supplied; see [source recovery](data/MAIN/provenance/source_recovery.json).

The current `.gitignore` excludes `data/*`, so a Git push alone does **not** transfer the final CSVs or their evidence. Share the `data/MAIN` folder through the team's chosen file transfer/data link as well as the code and docs. The raw CSVs total about 225 MB (decimal).

Topic approval is confirmed; dataset eligibility under the course's no-Kaggle rule remains unresolved in the available records. No models were fitted as part of this consolidation. The older 825-game run instructions are historical; the final dataset above supersedes that plan.
