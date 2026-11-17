# Chess blunder dataset: collect first, clean later

There are two main scripts in `Python Scripts/`:

- `PullLichessData.py`: collects the raw PGNs. It is unchanged.
- `Complexity.py`: reads every game and played move, calculates pre-move
  features, evaluates the moves with local Stockfish, and writes three CSVs.

Use **Run Python File** in VS Code, or run this from the project folder:

```bash
.venv/bin/python "Python Scripts/Complexity.py"
```

All games and moves are processed. There is no sampling, cleaning, splitting or
modeling. The full 90,000-game run has not been launched for you. Python needs no
internet, but the computer must stay on and awake.

## Settings and output

Edit the settings at the top:

- `DATA_DIR`: source PGNs, currently `data/results`.
- `OUTPUT_DIR`: a NEW folder, currently `data/position_dataset`.
- `STOCKFISH_PATH`: your installed Stockfish executable.
- `ENGINE_NODES = 100_000`, `THREADS = 1`, `HASH_MB = 128`.
- `BLUNDER_CP = 200`: ordinary losses must be strictly greater than 200cp.

A run creates `games_1m.csv`, `games_5m.csv`, `games_10m.csv` and
`engine_protocol.json`. The JSON keeps engine identity, settings, predictor and
target column names. It is not an execution summary.

Existing output folders are refused to avoid overwriting data. Change
`OUTPUT_DIR` to a new folder for another run. Rows are written progressively;
after interruption or error, the CSVs may be incomplete. **Finished all three
files** is printed only when the whole run succeeds.

## Script layout

- A. `get_board_features(board)`: 7 move counts and 40 board features.
- B. `get_player_features(headers, player)`: 4 rating/time-control features.
- C. `get_clock_features(...)`: the 7 clock features.
- D. `get_move_number(board)`: the game stage.
- E. `analyse_position(...)`, `pre_move_cp(...)`, `mate_info(...)` and
  `move_target(...)`: Stockfish scores and labeling.

`get_position_row(...)` first combines the ordinary pre-move features and
metadata. The processing loop then follows this order:

1. Search the pre-move board freely: `best_eval`.
2. Search the SAME board with `root_moves=[node.move]`: `played_eval`.
3. Extract `best_cp` and `played_cp` once, from the mover's perspective.
4. Save `best_cp` as `pre_eval_cp`, extract mate information, and pass the four
   already extracted values/statuses to `move_target(...)`.
5. Add metadata and results, write the row, then update the board and clocks.

Stockfish starts once in `run()` and is reused throughout. There are always two
searches per played move, even when the player chose the reported best move.
No existing PGN evaluations are used.

## Clocks and predictors

PGN clocks are AFTER the move. `clocks` and `last_spent` store earlier own clocks
and earlier move durations. The current annotation is read only after writing
the row. First-turn clocks are unknown. Missing annotations replace the previous
value with `None`. A previous-move duration needs two earlier own annotations.
Suspicious clocks and negative durations remain for cleaning; negative clocks
have no logarithm. Fractions use nominal starting time. Berserk and clock
adjustments need attention later. The estimate describes the start of the turn.

There are **60 candidate predictors**, listed in `PREDICTOR_COLUMNS` and the
protocol JSON. This includes `pre_eval_cp`, which uses only the pre-move board.
Actual moves, played-move scores, mate/status metadata and y stay OUT of X.

Each CSV has 84 columns: 60 predictors, 18 metadata columns and 6 target/audit
columns. Metadata includes game ID, ply, FEN, player, time control, raw White/Black
ratings, dates, source file, actual/best moves, search depths/node counts and both
evaluation statuses. These fields make later checks possible.

## Engine protocol and ordinary labels

Full board history is retained for repetition rules. Each search uses
`game=object()` for fresh engine search state. MultiPV is 1 and tablebases are
disabled. The explicit `info=...` argument is omitted; python-chess supplies the
usual analysis information.

The fixed node limit can stop an unfinished iteration. The script prefers the
latest unbounded score and PV together. Saved depth belongs to that result;
node count records total search work. The budget is not a fixed depth or a
guarantee of correct labels.

For two usable ordinary scores, from the same player's perspective:

```python
loss = best_cp - played_cp
y = int(loss > BLUNDER_CP)
```

Exactly 200cp gives y=0. Negative losses remain unchanged. Separate finite
searches can disagree, even for the reported best move, so labels can contain
search noise. These raw results are kept for later review.

Missing or bounded evaluations get y=None before applying any mate rules.
`best_eval_status` and `played_eval_status` distinguish `finite_cp`,
`winning_mate`, `losing_mate`, `missing_evaluation` and `bounded_score`.

## Forced-mate labels

Mate scores never become invented centipawn values. Original distances are saved
as `pre_mate` and `played_mate`. The evaluation statuses say whether the mate is
winning or losing for the mover. Both winning `MateGiven` and losing `Mate(0)`
return zero from `.mate()`, so score ordering is used to tell them apart.
See [python-chess mate scores](https://python-chess.readthedocs.io/en/latest/engine.html#chess.engine.Score.mate).

After checking missing/bounded scores, the rules are:

| Best continuation | Played continuation | y | label_status |
|---|---|---:|---|
| Winning mate | Ordinary score or losing mate | 1 | `missed_forced_win` |
| Ordinary score | Losing mate | 1 | `allowed_forced_loss` |
| Winning mate | Winning mate | 0 | `winning_mate_retained` |
| Losing mate | Losing mate | 0 | `already_forced_loss` |
| Ordinary score | Winning mate | 0 | `winning_mate_played` |
| Losing mate | Ordinary score or winning mate | blank | `inconsistent_mate_evaluations` |

Mate-distance changes are ignored. `eval_loss_cp` stays blank whenever either
score involves a mate. A previously losing mate followed by an ordinary/winning
score contradicts the first search, so it stays unclassified.

Target/audit columns are `played_eval_cp`, `pre_mate`, `played_mate`,
`eval_loss_cp`, `y` and `label_status`. CSV blanks mean `None`, not zero. Preserve
unclassified rows for cleaning; do not turn blank y values into 0.

## Later cleaning and project scope

The separate cleaning/modeling script should inspect clocks and missing values,
choose usable labels, and split whole games into train/validation/test. Fit
imputation and scaling only on training data. All 60 predictors are candidates;
many are correlated, so use regularized baselines and compare feature groups.
The objective is predictive, not causal.

Attack and hanging-piece counts are geometric proxies, including attacks by
pinned pieces. They do not prove a legal capture or material loss. "Own" means
the player about to move. Lichess ratings are Glicko-2, not FIDE ratings.

The raw collection has 30,000 games per time control but covers an early part of
1 October 2026, not a month-wide random sample. Topic approval is confirmed; the
course's no-Kaggle requirement remains unresolved. Related work exists, so do not
claim originality without comparison.

Earlier output folders used previous workflows and may have different columns,
predictors or labeling rules. The current script does not mix them into new CSVs.

References:

- [python-chess boards and moves](https://python-chess.readthedocs.io/en/latest/core.html)
- [python-chess engine interface](https://python-chess.readthedocs.io/en/latest/engine.html)
- [Lichess database](https://database.lichess.org/#standard_games)
- [Related prediction project](https://github.com/pm4o/Skill-Aware-Chess-Mistakes-Prediction)

## Candidate feature dictionary

These are the 60 candidate predictors, in CSV order.

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

## Verification on 17 November 2026

All 13 focused tests passed. They check preserved board calculations, scalar
label arguments, exactly two engine searches and one extraction of each cp
score per move, clock timing, mate-zero direction, the complete mate-rule matrix
for both colors, bounded/missing scores, all-game export and the 84-column CSV.

A real Stockfish test used six short games across all three controls, including
ordinary openings, Fool's Mate for either color and a missed mate in one. All
37 rows passed source-PGN checks for boards, ratings, prior clocks, moves, label
arithmetic and the CSV schema. The engine identified three newly allowed mates,
one missed forced win and two retained winning mates. These verify program
behavior, not perfect engine accuracy. Test files remain outside the project;
the full 90,000-game run was not launched.
