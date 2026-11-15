# for csvs
import csv
# for opening pgns
import io
# for saving information abt data collection
import json


from pathlib import Path

import chess
import chess.pgn
import chess.engine

# Editable settings. The installed script lives in the project's Python Scripts folder.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data/results"
OUTPUT_DIR = None                 # None creates a NEW timestamped output folder.
GAMES_PER_FILE = None                # Small first run: random games per control; None selects all.
POSITIONS_PER_GAME = None             # Random played moves per game; None selects all.
SEED = 2026
BLUNDER_CP = 200                  # Strictly MORE than 200 cp; exactly 200 gives y=0.
PROGRESS_EVERY = 10
STOCKFISH_PATH = Path("/home/jan/.local/share/org.encroissant.app/engines/stockfish/stockfish-linux-x86-64-universal")
ENGINE_NODES = 100_000             # Same work limit for each search, NOT a fixed depth.
THREADS = 1                       # One engine thread makes runs more reproducible.
HASH_MB = 128                     # Engine search-table memory, in MiB.
# MultiPV stays at 1: no expensive enumeration of alternative moves.
PGN_FILES = {"games_1m.pgn": "60+0", "games_5m.pgn": "300+0", "games_10m.pgn": "600+0"}



# 1. Cheap board features: one function per candidate predictor.


PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
                chess.ROOK: 500, chess.QUEEN: 900}


# Small helpers used by separate, named feature functions below.
def material(board, color, include_pawns=True):
    """Add ordinary piece values; kings have no material value here."""
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        if include_pawns or piece_type != chess.PAWN:
            total += len(board.pieces(piece_type, color)) * value
    return total


def doubled_pawns(board, color):
    """Count excess pawns beyond the first friendly pawn on each file."""
    counts = [0] * 8
    for square in board.pieces(chess.PAWN, color):
        counts[chess.square_file(square)] += 1
    #max returns
    return sum(max(0, count - 1) for count in counts)


def isolated_pawns(board, color):
    """Count pawns with no friendly pawn anywhere on either adjacent file."""
    pawns = list(board.pieces(chess.PAWN, color))
    files = {chess.square_file(square) for square in pawns}
    count = 0
    for square in pawns:
        file = chess.square_file(square)
        if file - 1 not in files and file + 1 not in files:
            count += 1
    return count


def passed_pawns(board, color):
    """Count pawns with no enemy pawn ahead on their file or an adjacent file."""
    count = 0
    for square in board.pieces(chess.PAWN, color):
        blocked = False
        for enemy in board.pieces(chess.PAWN, not color):
            nearby_file = abs(chess.square_file(enemy) - chess.square_file(square)) <= 1
            ahead = chess.square_rank(enemy) > chess.square_rank(square) if color == chess.WHITE else chess.square_rank(enemy) < chess.square_rank(square)
            if nearby_file and ahead:
                blocked = True
                break
        if not blocked:
            count += 1
    return count


def bishop_pair(board, color):
    """Require at least one bishop on each square color, including promoted bishops."""
    square_colors = set()
    for square in board.pieces(chess.BISHOP, color):
        square_colors.add((chess.square_file(square) + chess.square_rank(square)) % 2)
    return int(len(square_colors) == 2)


def king_zone_attacks(board, color):
    """Count enemy-attacked squares in the king square plus its adjacent squares."""
    king = board.king(color)
    if king is None:
        return 0
    zone = list(chess.SquareSet(chess.BB_KING_ATTACKS[king])) + [king]
    return sum(board.is_attacked_by(not color, square) for square in zone)


def pawn_shield(board, color):
    """Count friendly pawns one rank in front of the king, within one file."""
    king = board.king(color)
    if king is None:
        return 0
    front_rank = chess.square_rank(king) + (1 if color == chess.WHITE else -1)
    count = 0
    for square in board.pieces(chess.PAWN, color):
        if chess.square_rank(square) == front_rank and abs(chess.square_file(square) - chess.square_file(king)) <= 1:
            count += 1
    return count


def non_king_squares(board, color):
    """Return occupied friendly squares except the king."""
    return [square for square in chess.SquareSet(board.occupied_co[color])
            if board.piece_type_at(square) != chess.KING]


def pinned_pieces(board, color):
    """Count non-king pieces absolutely pinned to their own king."""
    return sum(board.is_pinned(color, square) for square in non_king_squares(board, color))


def attacked_pieces(board, color):
    """Count non-king pieces attacked geometrically by at least one enemy piece."""
    return sum(board.is_attacked_by(not color, square) for square in non_king_squares(board, color))


def hanging_squares(board, color):
    """Attacked, undefended non-king pieces; this is a geometric proxy."""
    return [square for square in non_king_squares(board, color)
            if board.is_attacked_by(not color, square) and not board.is_attacked_by(color, square)]


def rooks_on_open_files(board, color):
    """Count friendly rooks on files containing no pawn of either color."""
    pawn_files = {chess.square_file(square)
                  for square in board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)}
    return sum(chess.square_file(square) not in pawn_files for square in board.pieces(chess.ROOK, color))


# Move counts share one precomputed list of legal moves.
def legal_move_count(board, moves):
    """Number of legal moves for the player to move."""
    return len(moves)


def capture_move_count(board, moves):
    """Number of legal captures, including en passant."""
    return sum(board.is_capture(move) for move in moves)


def checking_move_count(board, moves):
    """Number of legal moves giving check."""
    return sum(board.gives_check(move) for move in moves)


def checking_capture_count(board, moves):
    """Number of legal moves that both capture and give check."""
    return sum(board.is_capture(move) and board.gives_check(move) for move in moves)


def quiet_move_count(board, moves):
    """Number of legal non-captures that do not give check; includes quiet castling."""
    return sum(not board.is_capture(move) and not board.gives_check(move) for move in moves)


def promotion_move_count(board, moves):
    """Number of legal promotion choices; each promotion piece counts separately."""
    return sum(move.promotion is not None for move in moves)


def castling_move_count(board, moves):
    """Number of castling moves legal right now."""
    return sum(board.is_castling(move) for move in moves)


def in_check(board):
    """Whether the player to move is in check."""
    return int(board.is_check())


def checker_count(board):
    """Number of pieces currently checking the player to move."""
    return len(board.checkers())


def material_balance_cp(board):
    """Own material minus opponent material, using fixed hand-written piece values."""
    return material(board, board.turn) - material(board, not board.turn)


def total_material_cp(board):
    """Total material of both players, excluding kings."""
    return material(board, chess.WHITE) + material(board, chess.BLACK)


def own_non_pawn_material_cp(board):
    """Mover's knight, bishop, rook and queen material."""
    return material(board, board.turn, include_pawns=False)


def opponent_non_pawn_material_cp(board):
    """Opponent's knight, bishop, rook and queen material."""
    return material(board, not board.turn, include_pawns=False)


def own_pawn_count(board):
    """Number of mover's pawns."""
    return len(board.pieces(chess.PAWN, board.turn))


def opponent_pawn_count(board):
    """Number of opponent's pawns."""
    return len(board.pieces(chess.PAWN, not board.turn))


def own_knight_count(board):
    """Number of mover's knights."""
    return len(board.pieces(chess.KNIGHT, board.turn))


def opponent_knight_count(board):
    """Number of opponent's knights."""
    return len(board.pieces(chess.KNIGHT, not board.turn))


def own_bishop_count(board):
    """Number of mover's bishops."""
    return len(board.pieces(chess.BISHOP, board.turn))


def opponent_bishop_count(board):
    """Number of opponent's bishops."""
    return len(board.pieces(chess.BISHOP, not board.turn))


def own_rook_count(board):
    """Number of mover's rooks."""
    return len(board.pieces(chess.ROOK, board.turn))


def opponent_rook_count(board):
    """Number of opponent's rooks."""
    return len(board.pieces(chess.ROOK, not board.turn))


def own_queen_count(board):
    """Number of mover's queens."""
    return len(board.pieces(chess.QUEEN, board.turn))


def opponent_queen_count(board):
    """Number of opponent's queens."""
    return len(board.pieces(chess.QUEEN, not board.turn))


def own_bishop_pair(board):
    """Whether the mover has bishops on both square colors."""
    return bishop_pair(board, board.turn)


def opponent_bishop_pair(board):
    """Whether the opponent has bishops on both square colors."""
    return bishop_pair(board, not board.turn)


def own_doubled_pawn_count(board):
    """Mover's excess pawns beyond one per file."""
    return doubled_pawns(board, board.turn)


def opponent_doubled_pawn_count(board):
    """Opponent's excess pawns beyond one per file."""
    return doubled_pawns(board, not board.turn)


def own_isolated_pawn_count(board):
    """Mover's pawns without a friendly pawn on an adjacent file."""
    return isolated_pawns(board, board.turn)


def opponent_isolated_pawn_count(board):
    """Opponent's pawns without a friendly pawn on an adjacent file."""
    return isolated_pawns(board, not board.turn)


def own_passed_pawn_count(board):
    """Mover's pawns with no enemy pawn ahead on their own or adjacent files."""
    return passed_pawns(board, board.turn)


def opponent_passed_pawn_count(board):
    """Opponent's pawns with no enemy pawn ahead on their own or adjacent files."""
    return passed_pawns(board, not board.turn)


def own_king_zone_attacked_count(board):
    """Enemy-attacked squares in the mover's king square and surrounding ring."""
    return king_zone_attacks(board, board.turn)


def opponent_king_zone_attacked_count(board):
    """Mover-attacked squares in the opponent's king square and surrounding ring."""
    return king_zone_attacks(board, not board.turn)


def own_pawn_shield_count(board):
    """Mover's friendly pawns one rank ahead of the king, within one file."""
    return pawn_shield(board, board.turn)


def opponent_pawn_shield_count(board):
    """Opponent's friendly pawns one rank ahead of the king, within one file."""
    return pawn_shield(board, not board.turn)


def own_castling_rights_count(board):
    """Mover's remaining castling rights (0, 1 or 2), not current castling legality."""
    return int(board.has_kingside_castling_rights(board.turn)) + int(board.has_queenside_castling_rights(board.turn))


def opponent_castling_rights_count(board):
    """Opponent's remaining castling rights (0, 1 or 2)."""
    return int(board.has_kingside_castling_rights(not board.turn)) + int(board.has_queenside_castling_rights(not board.turn))


def own_pinned_piece_count(board):
    """Mover's non-king pieces absolutely pinned to their king."""
    return pinned_pieces(board, board.turn)


def opponent_pinned_piece_count(board):
    """Opponent's non-king pieces absolutely pinned to their king."""
    return pinned_pieces(board, not board.turn)


def own_attacked_piece_count(board):
    """Mover's enemy-attacked non-king pieces; geometric attacks include pinned attackers."""
    return attacked_pieces(board, board.turn)


def opponent_attacked_piece_count(board):
    """Opponent's mover-attacked non-king pieces; geometric attacks include pinned attackers."""
    return attacked_pieces(board, not board.turn)


def own_hanging_piece_count(board):
    """Mover's attacked, undefended non-king pieces; a proxy, not guaranteed loss."""
    return len(hanging_squares(board, board.turn))


def opponent_hanging_piece_count(board):
    """Opponent's attacked, undefended non-king pieces; a proxy, not guaranteed loss."""
    return len(hanging_squares(board, not board.turn))


def own_hanging_material_cp(board):
    """Fixed material value of the mover's hanging pieces; excludes kings."""
    return sum(PIECE_VALUES[board.piece_type_at(square)] for square in hanging_squares(board, board.turn))


def opponent_hanging_material_cp(board):
    """Fixed material value of the opponent's hanging pieces; excludes kings."""
    return sum(PIECE_VALUES[board.piece_type_at(square)] for square in hanging_squares(board, not board.turn))


def own_rooks_on_open_files_count(board):
    """Mover's rooks on files with no pawns of either color."""
    return rooks_on_open_files(board, board.turn)


def opponent_rooks_on_open_files_count(board):
    """Opponent's rooks on files with no pawns of either color."""
    return rooks_on_open_files(board, not board.turn)


# Each entry is one feature function. Their docstrings become the feature dictionary.
MOVE_FEATURE_FUNCTIONS = [
    legal_move_count, capture_move_count, checking_move_count, checking_capture_count,
    quiet_move_count, promotion_move_count, castling_move_count,
]
BOARD_FEATURE_FUNCTIONS = [
    in_check, checker_count,
    material_balance_cp, total_material_cp, own_non_pawn_material_cp, opponent_non_pawn_material_cp,
    own_pawn_count, opponent_pawn_count, own_knight_count, opponent_knight_count,
    own_bishop_count, opponent_bishop_count, own_rook_count, opponent_rook_count,
    own_queen_count, opponent_queen_count, own_bishop_pair, opponent_bishop_pair,
    own_doubled_pawn_count, opponent_doubled_pawn_count, own_isolated_pawn_count,
    opponent_isolated_pawn_count, own_passed_pawn_count, opponent_passed_pawn_count,
    own_king_zone_attacked_count, opponent_king_zone_attacked_count,
    own_pawn_shield_count, opponent_pawn_shield_count,
    own_castling_rights_count, opponent_castling_rights_count,
    own_pinned_piece_count, opponent_pinned_piece_count,
    own_attacked_piece_count, opponent_attacked_piece_count,
    own_hanging_piece_count, opponent_hanging_piece_count,
    own_hanging_material_cp, opponent_hanging_material_cp,
    own_rooks_on_open_files_count, opponent_rooks_on_open_files_count,
]
FEATURE_FUNCTIONS = MOVE_FEATURE_FUNCTIONS + BOARD_FEATURE_FUNCTIONS
FEATURE_DEFINITIONS = {function.__name__: function.__doc__ for function in FEATURE_FUNCTIONS}


def get_board_features(board):
    """Return 47 numeric pre-move features; generate the legal move list once."""
    moves = list(board.legal_moves)
    result = {}
    for function in MOVE_FEATURE_FUNCTIONS:
        result[function.__name__] = function(board, moves)
    for function in BOARD_FEATURE_FUNCTIONS:
        result[function.__name__] = function(board)
    return result


# 2. Small context features: one function for each measurement.
def mover_elo(headers, player):
    """Rating of the player about to move."""
    return int(headers["WhiteElo" if player == chess.WHITE else "BlackElo"])


def opponent_elo(headers, player):
    """Rating of the other player."""
    return mover_elo(headers, not player)


def rating_difference(headers, player):
    """Mover's rating minus opponent's rating."""
    return mover_elo(headers, player) - opponent_elo(headers, player)


def initial_seconds(headers):
    """Nominal initial clock: 60, 300 or 600 seconds (zero increment in this dataset)."""
    return int(headers["TimeControl"].split("+")[0])


def clock_status(state, player):
    if state["moves_seen"][player] == 0:
        return "first_move_unknown"
    if state["problem"][player]:
        return "prior_clock_anomaly"
    if state["previous"][player] is None:
        return "missing_previous_annotation"
    return "previous_own_annotation_estimate"


def time_left_seconds(state, player):
    """Estimate at START of turn from the same player's previous annotation."""
    if clock_status(state, player) == "previous_own_annotation_estimate":
        return state["previous"][player]
    return None


def opponent_time_left_seconds(state, player):
    """Opponent's most recent clock, if its history is usable."""
    return time_left_seconds(state, not player)


def time_left_fraction(seconds, initial_seconds):
    """Remaining time divided by NOMINAL initial time, including for possible berserk."""
    return seconds / initial_seconds if seconds is not None else None


def clock_difference(seconds, opponent_seconds):
    """Mover's estimated seconds minus opponent's; missing if either is unknown."""
    return seconds - opponent_seconds if seconds is not None and opponent_seconds is not None else None


def time_left_log1p(seconds):
    """log(1+remaining seconds), a fixed transform emphasizing changes at low time."""
    return math.log1p(seconds) if seconds is not None else None


def low_time_10s(seconds):
    """Whether the estimated remaining clock is <=10 seconds; unknown stays missing."""
    return int(seconds <= 10) if seconds is not None else None


def last_move_seconds(state, player):
    """Time spent on the mover's previous move, from two earlier own annotations."""
    return state["last_spent"][player] if not state["problem"][player] else None


def move_number(board):
    """Full move number before the recorded move: 1 for both opening turns."""
    return board.fullmove_number


def pre_eval_cp(analysis, player):
    """Local Stockfish's PRE-MOVE evaluation, positive for the mover; mates stay missing."""
    if analysis.get("lowerbound") or analysis.get("upperbound"):
        return None
    return analysis["score"].pov(player).score()


CONTEXT_DEFINITIONS = {function.__name__: function.__doc__ for function in [
    mover_elo, opponent_elo, rating_difference, initial_seconds, time_left_seconds,
    opponent_time_left_seconds, time_left_fraction, clock_difference,
    time_left_log1p, low_time_10s, last_move_seconds, move_number, pre_eval_cp]}
PREDICTOR_COLUMNS = list(CONTEXT_DEFINITIONS) + list(FEATURE_DEFINITIONS)
# The columns below are for identification, data quality or target checks, NOT model inputs.
METADATA_COLUMNS = ["game_id", "split", "ply", "fen", "white_elo", "black_elo", "player_to_move",
                    "time_control", "utc_date", "utc_time", "source_pgn",
                    "clock_status", "opponent_clock_status", "before_eval_depth", "played_eval_depth",
                    "before_eval_nodes", "played_eval_nodes", "pre_mate"]
TARGET_COLUMNS = ["played_move", "engine_best_move", "played_eval_cp", "played_mate",
                  "eval_loss_cp", "y", "label_status"]


def game_split(game_id, seed):
    """One reproducible split per game, independent of its labels and sample size."""
    value = random.Random(f"{seed}:{game_id}").random()
    if value < 0.70:
        return "train"
    return "validation" if value < 0.85 else "test"


# 3. Read PGNs and select games with standard reservoir sampling (as in the collector).
def read_games(lines):
    current = []
    for line in lines:
        if line.startswith('[Event "') and current:
            yield "".join(current)
            current = []
        current.append(line)
    if current:
        yield "".join(current)


def sample_games(path, games_per_file, rng):
    selected = []
    scanned = 0
    with path.open(encoding="utf-8") as source:
        for text in read_games(source):
            scanned += 1
            if games_per_file is None or len(selected) < games_per_file:
                selected.append(text)
            else:
                position = rng.randrange(scanned)
                if position < games_per_file:
                    selected[position] = text
    rng.shuffle(selected)
    return selected, {"source_games": scanned, "selected_games": len(selected)}


# Analyze only the sampled positions. Existing PGN evaluations are never read.
def analyse_position(engine, board, nodes, root_moves=None):
    """Search the board, optionally allowing only one root move for target calculation."""
    if not any(board.legal_moves):
        return None  # Checkmate/stalemate has no move to predict.
    # A fresh game token sends ucinewgame: earlier target searches cannot affect features.
    analysis = None
    exact = None
    total_nodes = None
    with engine.analysis(board, chess.engine.Limit(nodes=nodes), game=object(),
                         root_moves=root_moves,
                         info=chess.engine.INFO_BASIC | chess.engine.INFO_SCORE | chess.engine.INFO_PV) as search:
        for info in search:
            if "nodes" in info:
                total_nodes = info["nodes"]
            if "score" in info and info.get("pv"):
                analysis = info.copy()  # Score, best move and depth from the SAME message.
                if not info.get("lowerbound") and not info.get("upperbound"):
                    exact = info.copy()
    # The budget can interrupt the next iteration. Prefer the last complete score/PV.
    analysis = exact if exact is not None else analysis
    if analysis is None:
        raise RuntimeError("Stockfish returned no score or best move.")
    analysis["nodes"] = total_nodes  # TOTAL work, including any interrupted iteration.
    return analysis


def move_target(before, played, move, player):
    """TARGET ONLY: best score minus score when the actual move is forced, same mover POV."""
    before_score = before["score"].pov(player)
    played_score = played["score"].pov(player)
    result = {"played_move": move.uci(), "engine_best_move": before["pv"][0].uci(),
              "played_eval_cp": played_score.score(), "played_mate": played_score.mate(),
              "eval_loss_cp": None, "y": None, "label_status": "finite_cp"}
    if before_score.is_mate() or played_score.is_mate():
        result["label_status"] = "mate_score"  # Including mate zero; no invented cp value.
    elif before.get("lowerbound") or before.get("upperbound") or played.get("lowerbound") or played.get("upperbound"):
        result["label_status"] = "bounded_score"
    else:
        loss = before_score.score() - played_score.score()
        result.update(eval_loss_cp=loss, y=int(loss > BLUNDER_CP))
        # Negative losses remain visible: separate finite searches can disagree.
    return result


# 4. Track only clock annotations that have already happened.
def new_clock_state():
    return {"previous": {True: None, False: None}, "moves_seen": {True: 0, False: 0},
            "problem": {True: False, False: False}, "last_spent": {True: None, False: None}}


def update_clock(state, player, current, initial_seconds):
    previous = state["previous"][player]
    if current is not None:
        if current < 0 or current > initial_seconds or (previous is not None and current > previous):
            state["problem"][player] = True
    spent = None
    if previous is not None and current is not None and not state["problem"][player]:
        spent = previous - current
    state["last_spent"][player] = spent
    state["previous"][player] = current
    state["moves_seen"][player] += 1


def position_features(game, board, analysis, state):
    """Predictors only. This function never reads the current move's after-clock/eval."""
    player = board.turn
    initial = int(game.headers["TimeControl"].split("+")[0])
    seconds = time_left_seconds(state, player)
    opponent_seconds = opponent_time_left_seconds(state, player)
    row = {"mover_elo": mover_elo(game.headers, player),
           "opponent_elo": opponent_elo(game.headers, player),
           "rating_difference": rating_difference(game.headers, player),
           "initial_seconds": initial_seconds(game.headers),
           "time_left_seconds": seconds, "opponent_time_left_seconds": opponent_seconds,
           "time_left_fraction": time_left_fraction(seconds, initial),
           "clock_difference": clock_difference(seconds, opponent_seconds),
           "time_left_log1p": time_left_log1p(seconds), "low_time_10s": low_time_10s(seconds),
           "last_move_seconds": last_move_seconds(state, player),
           "move_number": move_number(board), "pre_eval_cp": pre_eval_cp(analysis, player)}
    row.update(get_board_features(board))
    return row


def feature_rows(game, rng, positions_per_game, engine, nodes):
    plies = list(range(1, len(list(game.mainline())) + 1))
    number = len(plies) if positions_per_game is None else min(positions_per_game, len(plies))
    selected = set(rng.sample(plies, number))
    state = new_clock_state()
    board = game.board()
    headers = game.headers
    initial = int(headers["TimeControl"].split("+")[0])
    for ply, node in enumerate(game.mainline(), start=1):
        player = board.turn
        if ply in selected:
            before = analyse_position(engine, board, nodes)
            if before is not None:
                row = {"game_id": headers["Site"].rstrip("/").split("/")[-1], "ply": ply,
                       "fen": board.fen(), "white_elo": int(headers["WhiteElo"]),
                       "black_elo": int(headers["BlackElo"]),
                       "player_to_move": "white" if player == chess.WHITE else "black",
                       "time_control": headers["TimeControl"],
                       "utc_date": headers.get("UTCDate", ""), "utc_time": headers.get("UTCTime", ""),
                       "clock_status": clock_status(state, player),
                       "opponent_clock_status": clock_status(state, not player),
                       "before_eval_depth": before.get("depth"), "before_eval_nodes": before.get("nodes"),
                       "pre_mate": before["score"].pov(player).mate()}
                # All predictors are finished before looking at the move actually chosen.
                row.update(position_features(game, board, before, state))
                if node.move == before["pv"][0]:
                    played = before  # Best move already scored; no second search is needed.
                else:
                    played = analyse_position(engine, board, nodes, root_moves=[node.move])
                row.update(played_eval_depth=played.get("depth"), played_eval_nodes=played.get("nodes"))
                row.update(move_target(before, played, node.move, player))
                yield row
        # Update history even on unsampled moves, AFTER constructing the current row.
        update_clock(state, player, node.clock(), initial)
        board.push(node.move)


# 5. Build one streamed CSV and a small summary; never overwrite an existing folder.
def run(games_per_file=GAMES_PER_FILE, positions_per_game=POSITIONS_PER_GAME,
        output_dir=None, seed=SEED, data_dir=None, engine_nodes=ENGINE_NODES):
    for value in [games_per_file, positions_per_game, engine_nodes]:
        if value is not None and value < 1:
            raise ValueError("Sampling limits and search budget must be positive.")
    if engine_nodes is None:
        raise ValueError("Set a finite engine node budget.")
    if not STOCKFISH_PATH.is_file():
        raise FileNotFoundError(f"Set STOCKFISH_PATH to your engine executable: {STOCKFISH_PATH}")
    data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
    for name in PGN_FILES:
        if not (data_dir / name).is_file():
            raise FileNotFoundError(data_dir / name)
    if output_dir is None:
        output_dir = OUTPUT_DIR or PROJECT_DIR / "data" / time.strftime("stockfish_positions_%Y%m%d_%H%M%S")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    summary = {"status": "started", "seed": seed, "games_per_file": games_per_file,
               "chess_version": chess.__version__, "positions_per_game": positions_per_game,
               "blunder_threshold_cp": BLUNDER_CP, "label_source": "Local Stockfish; PGN evaluations ignored",
               "engine_protocol": {"path": str(STOCKFISH_PATH), "nodes_per_search": engine_nodes,
                                   "threads": THREADS, "hash_mib": HASH_MB, "multipv": 1,
                                   "fresh_search_state": True, "tablebases": "disabled",
                                   "score_selection": "Last unbounded score/PV; nodes record total search work",
                                   "target_search": "Same pre-move board, restricted to actual move; reuse if best"},
               "label_rule": "best_eval_cp - played_eval_cp > threshold, both from mover perspective",
               "sampling": "Random games per control, regardless of annotations; random played plies per game",
               "split_rule": "Game-ID seeded random assignment: 70% train, 15% validation, 15% test",
               "predictor_columns": PREDICTOR_COLUMNS, "target_columns": TARGET_COLUMNS,
               "source_files": [], "positions_saved": 0, "games_saved": 0,
               "limitations": ["Source collection is an early-October prefix, not a whole-month sample",
                               "Finite-budget engine labels are approximate; depth varies by position",
                               "Mate/bounded scores saved with missing y; filter label_status before modeling",
                               "Clocks estimated from prior annotations; unrecorded adjustments unknown"]}
    game_rng = random.Random(seed)
    position_rng = random.Random(seed + 1)
    seen_ids = set()
    columns = METADATA_COLUMNS + PREDICTOR_COLUMNS + TARGET_COLUMNS
    try:
        (output_dir / "predictor_columns.txt").write_text("\n".join(PREDICTOR_COLUMNS) + "\n")
        with chess.engine.SimpleEngine.popen_uci(str(STOCKFISH_PATH)) as engine:
            engine.configure({"Threads": THREADS, "Hash": HASH_MB, "SyzygyPath": ""})
            summary["engine_protocol"]["identity"] = engine.id
            print(f"{engine.id['name']}: {engine_nodes:,} nodes/search, {THREADS} thread(s), "
                  f"{HASH_MB} MiB hash, MultiPV=1", flush=True)
            with (output_dir / "positions.csv").open("x", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=columns)
                writer.writeheader()
                for filename, control in PGN_FILES.items():
                    texts, info = sample_games(data_dir / filename, games_per_file, game_rng)
                    info.update(filename=filename, time_control=control)
                    counts = Counter()
                    clock_counts = Counter()
                    info["counts"] = counts
                    info["clock_status_counts"] = clock_counts
                    summary["source_files"].append(info)
                    print(f"{filename}: {info['source_games']:,} source games; selected {len(texts):,}", flush=True)
                    for index, text in enumerate(texts, start=1):
                        game = chess.pgn.read_game(io.StringIO(text))
                        if game is None or game.errors:
                            counts["invalid_pgn_games"] += 1
                            continue
                        h = game.headers
                        if (h.get("Variant", "Standard") != "Standard" or "FEN" in h
                                or h.get("TimeControl") != control or not h.get("Event", "").startswith("Rated ")):
                            counts["invalid_header_games"] += 1
                            continue
                        game_id = h.get("Site", "").rstrip("/").split("/")[-1]
                        if not game_id or game_id in seen_ids:
                            raise ValueError(f"Missing/duplicate game ID: {game_id}")
                        seen_ids.add(game_id)
                        split = game_split(game_id, seed)
                        saved_game = False
                        for row in feature_rows(game, position_rng, positions_per_game, engine, engine_nodes):
                            row.update(source_pgn=filename, split=split)
                            writer.writerow(row)
                            if not saved_game:
                                summary["games_saved"] += 1
                                counts["games_saved"] += 1
                                counts[f"{split}_games"] += 1
                                saved_game = True
                            counts["positions"] += 1
                            counts[row["label_status"]] += 1
                            counts["blunders"] += int(row["y"] == 1)
                            counts[f"{split}_positions"] += 1
                            counts[f"{split}_blunders"] += int(row["y"] == 1)
                            if row["eval_loss_cp"] is not None:
                                counts["negative_eval_losses"] += int(row["eval_loss_cp"] < 0)
                            clock_counts[row["clock_status"]] += 1
                            summary["positions_saved"] += 1
                        if index % PROGRESS_EVERY == 0 or index == len(texts):
                            csv_file.flush()
                            print(f"  {index:,}/{len(texts):,} games; {summary['positions_saved']:,} rows; "
                                  f"{time.perf_counter() - started:.1f}s elapsed", flush=True)
        if summary["positions_saved"] == 0:
            raise ValueError("No positions were found in the sampled games.")
        summary["status"] = "completed"
    except (Exception, KeyboardInterrupt) as error:
        summary.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Completed: {summary['positions_saved']:,} positions from {summary['games_saved']:,} games "
          f"in {summary['elapsed_seconds']:.1f}s.\nOutput: {output_dir}", flush=True)
    return summary


if __name__ == "__main__":
    run()
