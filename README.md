# Chess blunder prediction: local Stockfish dataset builder

The workflow has two scripts in `Python Scripts/`:

1. `PullLichessData.py` collects raw games and stays unchanged.
2. `StockfishComplexity.py` samples positions, calculates 60 candidate predictors,
   and uses your installed Stockfish to calculate move labels. **Saved PGN evaluations
   are ignored completely. Unanalyzed games and first moves can be sampled.**

Run the second script with VS Code's **Run Python File** button, or from this folder:

```bash
.venv/bin/python "Python Scripts/StockfishComplexity.py"
```

The builder needs the installed `python-chess` package and the Stockfish executable.
No Internet connection is needed. Your computer must stay on and awake.

## Editable settings

The settings are at the top of the script:

- `GAMES_PER_FILE = 10`: randomly sample 10 games from each of the three PGNs.
- `POSITIONS_PER_GAME = 2`: randomly sample two played moves per selected game.
- `STOCKFISH_PATH`: the full path to your installed engine executable.
- `ENGINE_NODES = 100_000`: each engine search examines about 100,000 nodes.
- `THREADS = 1`, `HASH_MB = 128`: one CPU thread and 128 MiB engine search memory.
- `SEED = 2026`: reproducible game/position sampling and game splits.
- `BLUNDER_CP = 200`: strictly MORE than 200 centipawns; exactly 200 gives y=0.
- `OUTPUT_DIR = None`: create a new timestamped folder in `data/` for each run.

The defaults are a small pilot of about 60 rows. After checking it, changing
`GAMES_PER_FILE` to 1,000 aims for 6,000 rows, spread evenly across time controls.
Either sampling limit can be `None` for all games/positions, but analyzing every
move of all 90,000 games is unnecessary and much slower. The entire PGN is scanned
when sampling games, rather than taking its first games. This is reservoir
sampling, as in the collector. Positions are sampled without replacement, before
looking at their engine scores or labels. Games with very few moves contribute fewer rows.

## Engine protocol and target

The current installed engine reports **Stockfish 19**. Each run records its identity,
path, python-chess version and all search settings in `run_summary.json`.

For each sampled pre-move board:

1. Search all legal choices with MultiPV=1. Save its best move and score. This search
   depends only on the pre-move board and its previous move history.
2. Calculate the board, rating and clock predictors, including `pre_eval_cp`.
3. Search the SAME board again, restricting its first move to the move actually
   played. The engine searches replies normally. If the actual move was already
   the best move, reuse the first score instead of running a second search.
4. Convert both scores to the player-about-to-move's perspective and subtract:

   `eval_loss_cp = best score - played-move score`

   `y = 1 if eval_loss_cp > 200, otherwise 0`

This avoids analyzing every legal move separately. The score of the played move
is measured at the pre-move root; the output calls it `played_eval_cp`, rather than
misleadingly calling it an independent after-position evaluation.

Both searches use the same fixed node budget, one thread, 128 MiB hash, MultiPV=1,
full engine strength and no external tablebases. Each search starts with fresh
search state (`ucinewgame`), preventing earlier target searches from influencing
later predictor scores. The board's move history is preserved for repetition rules.

A node is one position visited during search. A fixed node budget controls work;
it is **not a promised depth**. The depth of the last complete, unbounded score and the actual TOTAL node count
are saved for each search, as audit metadata rather than predictors. A partial
iteration at the node limit is ignored when an earlier complete score exists.
The saved best move and score always come from the same complete iteration. Small budget overruns
are normal. Depth varies by position, and two different searches can disagree.
Negative evaluation losses are retained, not clipped. They get y=0 and indicate
finite-search noise; labels near 200cp deserve stronger-search checks before final modeling.
No fixed node budget guarantees correct labels.

Mate scores (including mate zero) are saved separately in `pre_mate`/`played_mate`.
The row remains in the CSV with `label_status = mate_score` and missing `y` and
`eval_loss_cp`. No arbitrary huge centipawn value is substituted. A final bounded
score likewise gets `label_status = bounded_score` and no label. Use only
**`label_status == "finite_cp"` rows** for the initial classifier. Checkmate and
stalemate positions have no next move to predict; a terminal-board helper call
returns no analysis. A played move that causes a draw or checkmate is still
analyzed; a mate result follows the missing-label rule above. A position with
one legal move needs just one search and has zero finite evaluation loss.

## Output, clocks and leakage

Each new `data/stockfish_positions_YYYYMMDD_HHMMSS/` folder contains:

- `positions.csv`: one row per sampled pre-move decision, including nullable labels.
- `predictor_columns.txt`: the 60 candidate predictor names to use for X.
- `run_summary.json`: engine protocol, sampling, label counts, limitations and timing.

Use a run only if its summary says `completed`. Failed/interrupted runs may leave
partial output. Existing output folders are refused. Rows are written progressively;
only the current file's selected PGN texts are held in memory. Earlier annotation-based
datasets remain in their existing folders and are not rebuilt or mixed into new runs.
Their timings and label definitions do not apply to this engine-based builder.

All predictors describe information available **before** the current move. The
chosen move and its restricted engine search belong only to target calculation.
Current after-move clocks are consumed after creating the current row.

Remaining time estimates the START of a turn from the same player's previous clock
annotation. First-move clocks are unknown, since nominal time can differ under
berserk. Missing annotations remain missing. Prior clock increases or out-of-range
values suppress subsequent clock estimates for that player. `last_move_seconds`
uses two earlier own annotations. Clock fractions use nominal starting time.
Unrecorded adjustments during the opponent's turn cannot be reconstructed.

`split` assigns entire game IDs to approximately 70% training, 15% validation and
15% test, using a seeded rule independent of labels. For cross-validation within
training, group by game ID again. Fit imputation, scaling and feature selection
on training folds only. Recurring players can appear across game splits: this
measures generalization to other games, not necessarily unseen players.

Only use the predictor whitelist for X. IDs, FEN, split, source filename, chosen
move, engine best move, played score, mate metadata, evaluation loss, label status,
search depth/node metadata and y must stay out of X. White/Black ratings are
retained as metadata; candidate predictors use mover/opponent Lichess Glicko-2
ratings. Consider time controls categorical. `pre_eval_cp` is a permitted pre-move
engine feature; omit it when comparing a board-only model.

## Feature use and project scope

Each candidate feature has its own small function, with shared helpers for common
counts. There is no combined complexity score. There are 47 cheap board measurements
and 13 rating/time/context features. Keep the useful feature groups and compare
rating/time baselines with added board features. Many columns are correlated or
algebraically related; use regularization rather than blindly fitting every column.

Counts of alternatives within 50cp, alternatives losing 200cp, and best-second
score gaps remain omitted. MultiPV=1 does not score every legal alternative, so
we cannot report those counts from this search. Legal captures/checks are counted
exactly with python-chess and require no extra engine searches.

"Own" means the player to move. Capture and check counts overlap. Attack, hanging
piece and king-zone counts are geometric proxies, including attacks by pinned
pieces. They do not guarantee a legal capture or material loss. Pawn structure,
material and king safety are possible predictors, not certified human difficulty.

All 90,000 source games can now be sampled, regardless of saved evaluations.
However, the raw collection covers an early part of **1 October 2026**, not a
month-wide random sample. Topic approval is confirmed; eligibility under the
course's no-Kaggle rule remains unresolved. The idea overlaps existing work and
should not be claimed as new. The project is predictive, not causal.

References:

- [python-chess engine interface](https://python-chess.readthedocs.io/en/latest/engine.html)
- [python-chess board operations](https://python-chess.readthedocs.io/en/latest/core.html)
- [Stockfish developer documentation](https://official-stockfish.github.io/docs/stockfish-wiki/Developers.html)
- [Lichess standard-game database](https://database.lichess.org/#standard_games)
- [Related prediction project](https://github.com/pm4o/Skill-Aware-Chess-Mistakes-Prediction)

## Candidate feature dictionary

The table below lists the output name, its small function and its precise meaning.

| Column and feature function | Definition |
|---|---|
| `mover_elo` | Rating of the player about to move. |
| `opponent_elo` | Rating of the other player. |
| `rating_difference` | Mover's rating minus opponent's rating. |
| `initial_seconds` | Nominal initial clock: 60, 300 or 600 seconds (zero increment in this dataset). |
| `time_left_seconds` | Estimate at START of turn from the same player's previous annotation. |
| `opponent_time_left_seconds` | Opponent's most recent clock, if its history is usable. |
| `time_left_fraction` | Remaining time divided by NOMINAL initial time, including for possible berserk. |
| `clock_difference` | Mover's estimated seconds minus opponent's; missing if either is unknown. |
| `time_left_log1p` | log(1+remaining seconds), a fixed transform emphasizing changes at low time. |
| `low_time_10s` | Whether the estimated remaining clock is <=10 seconds; unknown stays missing. |
| `last_move_seconds` | Time spent on the mover's previous move, from two earlier own annotations. |
| `move_number` | Full move number before the recorded move: 1 for both opening turns. |
| `pre_eval_cp` | Local Stockfish's pre-move evaluation, positive for the mover; missing for mates/bounds. |
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


## Verification on 15 November 2026

All 15 focused tests passed on the installed script. They cover strict 200cp
thresholds, both score perspectives, mates including zero, score bounds, no
annotation dependency, first moves, leakage, clock history, sampling, forced
moves, terminal boards, whole-game splits and protected output folders.

Both installed-script runs below used Stockfish 19 with 100,000 nodes/search,
one thread, 128 MiB hash and MultiPV=1. These are measured local timings.

| Run | Games | Rows | Finite labels | Mate rows | Blunders | Elapsed |
|---|---:|---:|---:|---:|---:|---:|
| Default pilot | 30 | 60 | 58 | 2 | 3 | 30.6 s |
| Larger sample | 300 | 600 | 564 | 36 | 59 | 271.6 s |

All rows passed checks of labels, legal moves, all 47 board measurements, numeric
values, ratings, clocks, duplicate positions, game splits and summary counts.
Twenty rows per run were also checked directly against their source PGNs for
board reconstruction, chosen moves, ratings and prior clock history.

The larger sample has 200 sampled rows per time control, before excluding mate
labels. It is a tested example, not a final modeling dataset. At this measured
throughput, 6,000 sampled rows would take roughly 45–55 minutes, depending on
positions and computer load. This is a runtime estimate, not a label-quality test.
Stronger-search checks remain necessary to assess threshold stability.

New datasets:

- `data/stockfish_pilot_60_20261115/positions.csv`
- `data/stockfish_sample_600_20261115/positions.csv`

Each contains a `verification.json` record. Earlier `annotated_*` datasets use
the previous saved-evaluation method and should not be mixed with these runs.
The raw PGNs and collector were preserved.
