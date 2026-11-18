# Predicting blunders in online chess

**University of St. Gallen — Fundamentals of Data Science, Fall 2026**
**Deadline: 30 November 2026**

We predict the probability that a player's next move will be a blunder. Our main question is whether simple measurements of the position improve prediction beyond the players' ratings, time control and available clock time. We study prediction, not whether complexity causes mistakes.

Each observation is the position **immediately before one player makes one move**. A single player's move is called a **ply**; White moving and then Black moving are two plies. Features describe the position before that ply, while Stockfish evaluates the actual move afterward to construct the target `y`.

We keep complexity decomposed into understandable features: legal choices, captures, checks, material, pawn structure, king safety and attacks. There is no combined “complexity score”. Pre-move Stockfish evaluation measures advantage and will be assessed separately from these elementary position features. Predicting how an opponent exploits a mistake is outside the current scope.

## Where we are now

Game collection and Stockfish labeling are complete. The shared starting point is the three **raw, uncleaned CSVs** in [`data/600000_Databasis/`](data/600000_Databasis/). The folder name is approximate: the exact number is **586,827 position rows from 9,000 games**.

| Time control | Raw file | Games | Raw positions | Valid labels | Blunders |
|---|---|---:|---:|---:|---:|
| 1+0 | `games_1m.csv` | 3,000 | 194,221 | 194,191 | 23,113 |
| 5+0 | `games_5m.csv` | 3,000 | 202,576 | 202,549 | 22,507 |
| 10+0 | `games_10m.csv` | 3,000 | 190,030 | 190,007 | 21,826 |
| **Total** | | **9,000** | **586,827** | **586,747** | **67,446** |

All 80 blank labels are `inconsistent_mate_evaluations`; they stay unclassified. The blunder rate among valid labels is approximately **11.5%**. Final cleaned CSVs were not transferred to this PC. The team will clean these raw inputs independently; no models have been fitted in this handoff.

## Current folder structure

```text
lichess_90k_sampling_starter/
├── README.md
├── requirements.txt
├── Python Scripts/
│   ├── PullLichessData.py
│   ├── Complexity.py
│   ├── CleanData.py
│   └── Sampling from SampledDataset (for PoC)/
│       └── PrepareGames.py
├── data/
│   ├── 90'000_Games/                  Original PGNs and game metadata
│   ├── 600000_Databasis/              Final raw position CSVs
│   │   └── provenance/                Run records, hashes and recovered run source
│   └── Old_Pilots/
│       ├── InitialOvernightSubset/    Actual 3-game and 30-game pilot evidence
│       └── MicroPilot/               Actual 825-game starting PGN subset
├── docs/                              Dataset, feature and team documentation
└── stockfish/                         Matching Stockfish distribution
```

The two pilot folder names do not describe their sizes: `MicroPilot` holds **825 games / 54,262 plies**, while `InitialOvernightSubset` holds the **3-game and 30-game pilots**. These are historical inputs/results, not additional final training data.

Some script defaults and older documents still refer to the previous names `data/results`, `data/MAIN` or `data/run_input_20261118`. The paths above are the current locations. Before reusing a script, set its input/output paths explicitly. No new download or engine run is needed to start cleaning the existing CSVs.

## 1. Collecting games — PullLichessData.py

[`PullLichessData.py`](<Python Scripts/PullLichessData.py>) reads the compressed Lichess archive and saves games in three separate PGNs. A **PGN** is a text record containing game headers, moves and annotations such as clocks. The script preserves that original game text instead of replacing it with a position table.

The script has seven logical sections:

| Section | What it does | Main settings/functions |
|---|---|---|
| 1. Imports and settings | Select month, time controls, sample size, scan limit, seed and output folder. | `MONTH`, `GAMES_PER_CONTROL`, `MAX_GAMES`, `SEED`, `OUTPUT_DIR` |
| 2. Read individual games | Accumulate lines until the next `[Event ...]` header; extract headers into a dictionary. | `read_games()`, `read_headers()` |
| 3. Filter eligible games | Keep rated standard completed games at 1+0, 5+0 or 10+0, with valid IDs/ratings and no identified bots. | `usable_headers()` |
| 4. Sample while reading | Maintain a separate random candidate pool for each time control. | `sample_games()` |
| 5. Validate candidates | Parse legal moves, require nonnegative clock annotations and check result consistency. | `check_game()` |
| 6. Save accepted games | Reject duplicate IDs, write the three PGNs and one metadata CSV row per game. | `save_games()` |
| 7. Run the workflow | Open a remote/local archive, decompress it as a stream, run the steps and save a collection summary. | `run()` |

Section 4 uses **reservoir sampling**: after the pool fills, each later eligible game gets a random chance to replace a stored game. This samples without keeping the whole archive in memory. Pools hold 20% extra candidates so invalid games can be replaced during validation.

The inspected settings are October 2026, 30,000 games per control, seed 2026 and a scan limit of 1,000,000 archive games. Sampling is random within the portion actually scanned. Because the collector stopped early, our saved 90,000 games span **1 October 2026, 00:00:02–10:45:57 UTC**. They are **not a random sample across the full month**.

The source files now in [`data/90'000_Games/`](data/90%27000_Games/) are:

- `games_1m.pgn`, `games_5m.pgn`, `games_10m.pgn`: 30,000 games each.
- `games_metadata.csv`: game IDs, players, ratings, dates, time controls and ply counts.
- `collection_summary.json`: sampling settings and collection status.

The pool contains **5,893,244 played plies**. It is the source pool; the final Stockfish dataset uses 9,000 of those games.

## 2. Building position rows — Complexity.py

[`Complexity.py`](<Python Scripts/Complexity.py>) replays each PGN using `python-chess`. A `board` object represents the current position. `board.legal_moves` supplies legal choices, while piece and attack methods supply the cheap features. Stockfish supplies the engine evaluations used to label the actual move.

### The six sections

| Section | What it defines | Measurements |
|---|---|---:|
| 1. Move features | Legal moves, captures, checks, quiet moves, promotions and castling. | 7 |
| 2. Board features | Material, pieces, pawns, king safety, pins, attacks and hanging pieces. | 40 |
| 3. Game features | Mover/opponent ratings, rating difference and nominal starting time. | 4 |
| 4. Clock features | Previous available clocks, fractions, clock difference, low time and previous move duration. | 7 |
| 5. Move number | Full move number, to contextualize the stage of the game. | 1 |
| 6. Stockfish and target | Pre-move evaluation, best/played comparisons, mate handling and `y`. | 1 predictor plus target/audit values |

Sections 1–5 use the same pattern: **individual feature functions → list of functions → collector**. For example, `MOVE_FEATURE_FUNCTIONS` holds the move functions, and `get_move_features()` calls each one. Its name becomes the output column name. Adding a function to the list makes it available to the collector and generated column list.

`get_all_features()` joins the first five collectors into **59 ordinary pre-move measurements**. Section 6 adds `pre_eval_cp`, giving **60 candidate predictors**. The target `y` and diagnostic values are saved separately; they are not another group of predictors.

### How one game becomes rows

`process_pgn()` follows this order:

1. Read a game and record any PGN errors as diagnostic rows.
2. Extract constant game metadata once, then initialize its board and clock history.
3. Before each played move, copy the metadata and calculate all ordinary predictors.
4. Save that pre-move FEN, ply, player and actual move as metadata. **FEN** is a text description of a board position; it is not a model input here.
5. Ask Stockfish for its best continuation and, when necessary, the continuation with the actual move forced at the root of the same board.
6. Extract scores from the mover's perspective, assign `y` and record search diagnostics.
7. Write the CSV row, then advance the board and read the current after-move clock for use in later rows.

Game metadata is reused through a fresh dictionary copy for each row. Board/clock features are recalculated each move. No terminal position after the final played move is added, because there is no next human move to label.

### Engine protocol and the final run

| Setting | Recorded value |
|---|---|
| Engine | Stockfish 19 |
| Search budget | 100,000 nodes per search |
| Engine threads | 1 per engine |
| Hash memory | 128 MiB per engine |
| MultiPV | 1 |
| Tablebases | Disabled |
| Search state | Fresh for each search; full board history retained |
| Evaluation perspective | Player about to move |

A **node** is a position visited during search. Fixed nodes give a computational budget, not a fixed depth or a guarantee of correctness. The last unbounded score/PV is retained together, with its depth and total search nodes. A **PV** is the engine's preferred continuation; “unbounded” means the reported score is not marked as a search bound, not that the position is solved.

When the actual move equals the unrestricted search's best PV move, the script reuses that result. Otherwise it performs a second search restricted to the actual move. It does not evaluate every legal alternative or calculate best–second-best gaps/acceptable-move counts. Existing PGN evaluation annotations are not used.

The home-PC run used **12 parallel workers, each controlling a separate one-thread Stockfish engine**. The overnight runner added per-game checkpoints, resumption on relaunch, verification and publication. Its selection extended the original 275 games per control to 3,000 per control, using the recorded seeded plan and excluding the 30 pilot games. All 9,000 game IDs/plies and the selection order were checked against the recovered runner.

The original readable `Python Scripts/Complexity.py` remains in place. The exact home-PC exporter and runner are archived under [`provenance/home_pc_source/`](data/600000_Databasis/provenance/home_pc_source/). Their existing feature/clock/label/move-processing functions are unchanged; the home copy adapts the Stockfish connection and startup handling. Its restored file hash exactly matches the run manifest. That archive is source evidence, not a script to launch directly from its nested folder.

## 3. Target y, clocks and leakage

For two usable finite centipawn scores:

```python
eval_loss_cp = best_cp - played_cp
y = int(eval_loss_cp > 200)
```

Scores use the **same mover's perspective**, whether White or Black. A loss of exactly 200cp is y=0. Negative estimated losses are preserved as finite-search disagreements.

Mate scores have separate rules and are never converted into fabricated centipawn values:

| Best continuation | Played continuation | y |
|---|---|---:|
| Winning mate | Finite score or losing mate | 1 |
| Finite score | Losing mate | 1 |
| Winning mate | Winning mate | 0 |
| Losing mate | Losing mate | 0 |
| Finite score | Winning mate | 0 |
| Losing mate | Finite score or winning mate | blank |
| Missing or bounded evaluation | Any | blank |

Changes in mate distance alone are ignored. The 80 blank labels in the final CSVs are all inconsistent losing-mate comparisons. They must not become zeros during cleaning. The pilot's stronger-budget check agreed on 29/30 labels; that is budget agreement, not certified label accuracy.

PGN clocks are **after-move annotations**. The current move's annotation is read only after its row is written. Pre-turn time is estimated from the same player's previous annotation; first own clocks stay missing. `last_move_seconds` describes the mover's **previous** move and needs two earlier own annotations. Clock adjustments and suspicious values remain in the raw CSV for cleaning.

Raw CSV order is **`y` + 60 predictors + one visual spacer + 24 metadata columns = 86 columns**. The spacer is named one space, `" "`. The metadata contains IDs/FEN, actual/best moves, played scores, mate/status information, evaluation loss and search details.

Use [`provenance/predictor_columns.json`](data/600000_Databasis/provenance/predictor_columns.json) or `Complexity.PREDICTOR_COLUMNS` to select X. **Dropping only y is insufficient:** some metadata directly reveals the target. `pre_eval_cp` is the allowed engine predictor because it uses the pre-move board.

## 4. All candidate predictors

“Own” means the player about to move. Material uses fixed hand-written values (pawn 100, knight 320, bishop 330, rook 500, queen 900), excluding kings. Attack/hanging-piece measurements are geometric proxies; pinned pieces can still count as attackers, and an attacked/undefended piece is not necessarily legally capturable or certain to be lost. Ratings are Lichess ratings, despite the column names using `elo`.

The following are the **60 raw candidate predictors**, in CSV order. The reference cleaner adds a separate `pre_eval_cp_missing` flag; it is not a new Stockfish search.

| Column | Definition |
|---|---|
| `legal_move_count` | Number of legal moves for the player to move. |
| `capture_move_count` | Number of legal captures, including en passant. |
| `checking_move_count` | Number of legal moves giving check. |
| `checking_capture_count` | Number of legal moves that both capture and give check. |
| `quiet_move_count` | Number of legal non-captures that do not give check; includes quiet castling. |
| `promotion_move_count` | Number of legal promotion choices; each promotion piece counts separately. |
| `castling_move_count` | Number of castling moves legal right now. |
| `in_check` | Whether the player to move is in check. |
| `checker_count` | Number of pieces currently checking the player to move. |
| `material_balance_cp` | Own material minus opponent material, using fixed hand-written piece values. |
| `total_material_cp` | Total material of both players, excluding kings. |
| `own_non_pawn_material_cp` | Mover's knight, bishop, rook and queen material. |
| `opponent_non_pawn_material_cp` | Opponent's knight, bishop, rook and queen material. |
| `own_pawn_count` | Number of mover's pawns. |
| `opponent_pawn_count` | Number of opponent's pawns. |
| `own_knight_count` | Number of mover's knights. |
| `opponent_knight_count` | Number of opponent's knights. |
| `own_bishop_count` | Number of mover's bishops. |
| `opponent_bishop_count` | Number of opponent's bishops. |
| `own_rook_count` | Number of mover's rooks. |
| `opponent_rook_count` | Number of opponent's rooks. |
| `own_queen_count` | Number of mover's queens. |
| `opponent_queen_count` | Number of opponent's queens. |
| `own_bishop_pair` | Whether the mover has bishops on both square colors. |
| `opponent_bishop_pair` | Whether the opponent has bishops on both square colors. |
| `own_doubled_pawn_count` | Mover's excess pawns beyond one per file. |
| `opponent_doubled_pawn_count` | Opponent's excess pawns beyond one per file. |
| `own_isolated_pawn_count` | Mover's pawns without a friendly pawn on an adjacent file. |
| `opponent_isolated_pawn_count` | Opponent's pawns without a friendly pawn on an adjacent file. |
| `own_passed_pawn_count` | Mover's pawns with no enemy pawn ahead on their own or adjacent files. |
| `opponent_passed_pawn_count` | Opponent's pawns with no enemy pawn ahead on their own or adjacent files. |
| `own_king_zone_attacked_count` | Enemy-attacked squares in the mover's king square and surrounding ring. |
| `opponent_king_zone_attacked_count` | Mover-attacked squares in the opponent's king square and surrounding ring. |
| `own_pawn_shield_count` | Mover's friendly pawns one rank ahead of the king, within one file. |
| `opponent_pawn_shield_count` | Opponent's friendly pawns one rank ahead of the king, within one file. |
| `own_castling_rights_count` | Mover's remaining castling rights (0, 1 or 2), not current castling legality. |
| `opponent_castling_rights_count` | Opponent's remaining castling rights (0, 1 or 2). |
| `own_pinned_piece_count` | Mover's non-king pieces absolutely pinned to their king. |
| `opponent_pinned_piece_count` | Opponent's non-king pieces absolutely pinned to their king. |
| `own_attacked_piece_count` | Mover's enemy-attacked non-king pieces; geometric attacks include pinned attackers. |
| `opponent_attacked_piece_count` | Opponent's mover-attacked non-king pieces; geometric attacks include pinned attackers. |
| `own_hanging_piece_count` | Mover's attacked, undefended non-king pieces; a proxy, not guaranteed loss. |
| `opponent_hanging_piece_count` | Opponent's attacked, undefended non-king pieces; a proxy, not guaranteed loss. |
| `own_hanging_material_cp` | Fixed material value of the mover's hanging pieces; excludes kings. |
| `opponent_hanging_material_cp` | Fixed material value of the opponent's hanging pieces; excludes kings. |
| `own_rooks_on_open_files_count` | Mover's rooks on files with no pawns of either color. |
| `opponent_rooks_on_open_files_count` | Opponent's rooks on files with no pawns of either color. |
| `mover_elo` | Rating of the player about to move. |
| `opponent_elo` | Rating of the other player. |
| `rating_difference` | Mover's rating minus opponent's rating. |
| `initial_seconds` | Nominal initial clock: 60, 300 or 600 seconds (zero increment in this dataset). |
| `time_left_seconds` | Estimate at START of turn from the same player's previous annotation. |
| `opponent_time_left_seconds` | Opponent's most recent earlier clock annotation; missing stays missing. |
| `time_left_fraction` | Remaining time divided by nominal initial time; missing when the initial time is not positive. |
| `clock_difference` | Mover's estimated seconds minus opponent's; missing if either is unknown. |
| `time_left_log1p` | log(1+remaining seconds); missing for unknown or negative clocks. |
| `low_time_10s` | Whether the estimated remaining clock is <=10 seconds; unknown stays missing. |
| `last_move_seconds` | Time spent on the mover's previous move, from two earlier own annotations. |
| `move_number` | Full move number before the recorded move: 1 for both opening turns. |
| `pre_eval_cp` | Local Stockfish pre-move evaluation, positive for the mover; missing for mates, bounds or missing scores. |

## 5. Where we go next

### Independent cleaning

Each teammate starts from the same raw CSVs in `data/600000_Databasis/` and saves cleaned outputs separately. [`CleanData.py`](<Python Scripts/CleanData.py>) is a reference implementation; it imports the schema and clock helpers from `Complexity.py`. Its default paths belong to an older layout, so pass current paths explicitly if reusing it.

Cleaning should record what was changed:

- Exclude diagnostic/invalid/duplicate rows and rows with no valid binary y. Removing only the 80 unclassified rows leaves **586,747 labeled observations**.
- Keep valid mate-labeled rows even when `pre_eval_cp` or played centipawn scores are missing. Ordinary scores have no mate value, and mate scores have no ordinary cp value. Avoid blanket `dropna()`.
- Detect suspicious clocks chronologically within each game/player, using only history available by that turn. Mask affected clocks and recompute their derived features rather than discarding all other measurements.
- Keep negative evaluation losses and inspect extreme scores instead of automatically clipping/removing them.
- Remove the visual spacer and save a report of rows/games retained, exclusions, missingness and class counts by time control. The reference cleaner also adds `pre_eval_cp_missing` and leaves numerical missingness blank.

Final cleaned CSVs/report are not on this PC yet. The processing-PC context reports 586,747 reference-cleaner rows across all 9,000 games; these are comparison counts, not a newly reproduced cleaning result here.

### Modeling and evaluation

1. Freeze an 80/20 split of **whole games**, balancing time controls. Save game IDs. No game may cross training/test or cross-validation folds.
2. Within training, use game-grouped cross-validation for tuning. Fit imputation, scaling and encoding inside each training fold, never on the complete dataset.
3. Compare the following on the same eligible rows:

| Model | Inputs |
|---|---|
| M0 | Constant training-set blunder frequency |
| M1 | Ratings, time control, clocks and move number |
| M2 | M1 plus elementary move/board features |
| M3 | M2 plus pre-move evaluation and its missing-value indicator |

Use L2-regularized logistic regression for M1–M3, treating time control as categorical. Check class/group counts before choosing ten grouped folds; document any reduction needed. Choose regularization and classification thresholds on validation only, then evaluate the locked procedure once on test.

Report average precision, log loss, Brier score and a reliability diagram with bin counts, plus precision/recall/F1 at the validation-selected threshold. Keep the pre-evaluation missing flag out of M1/M2 so the engine-feature comparison remains separate. Brier score measures overall probability quality; the reliability diagram helps examine calibration.

Positions from one game remain dependent even after feature extraction. Repeated players can cross game splits, so results concern unseen games, not necessarily unseen players or new calendar periods. Record these limits and engine-label uncertainty in the report.

### Finish the project

Use the cleaned-data report, frozen splits, baseline/feature-group comparisons and error analysis to write the final report and presentation. Make the notebook reproducible with saved seeds and clear feature whitelists. Complete the submission by **30 November 2026**.

Topic approval is confirmed. Dataset eligibility under the course's no-Kaggle rule remains unresolved in the available records. Related prediction work exists, so no originality claim is made here.

## Supporting records and sharing

- [Team handoff](docs/TEAM_HANDOFF.md), [dataset record](docs/DATASET_9000.md) and [feature dictionary](docs/FEATURE_DICTIONARY.md) provide further detail. Some older paths in those records predate the folder renames; use this README's current folder map.
- [Pilot report](docs/GPT_Pilotreport.md): 30 games / 1,550 positions in 15 minutes 24 seconds on the original one-engine setup, with 185 blunders among valid labels.
- [`provenance/`](data/600000_Databasis/provenance/): run manifest, engine protocol, exact 9,000-game membership, raw CSV hashes, validation and recovered source. Original source hashes, schema, IDs/plies, duplicate keys and finite-label arithmetic were checked during consolidation. These checks do not establish engine-label ground truth.
- `stockfish/` preserves the matching executable, source and license. Python dependencies are listed in `requirements.txt`; a copied virtual environment should be recreated on another computer.

The current `.gitignore` excludes `data/*`. A Git push alone does **not** include the final CSVs or their provenance. Share the data folder/link alongside the code and documentation; the three final raw CSVs total about 225 MB (decimal).
