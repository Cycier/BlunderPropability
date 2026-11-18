# Candidate predictor dictionary

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

The raw schema is unchanged in the final 9,000-game delivery. For target and metadata exclusions, see [DATASET_9000.md](DATASET_9000.md).
