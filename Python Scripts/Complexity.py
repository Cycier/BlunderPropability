# for csvs
import csv
# for saving the Stockfish settings
import json
# for calculating log time
import math
from pathlib import Path

import chess
import chess.pgn
import chess.engine

# This script lives in "Python Scripts", one folder below the project folder.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data/results"
OUTPUT_DIR = PROJECT_DIR / "data/position_dataset"
PGN_FILES = ["games_1m.pgn", "games_5m.pgn", "games_10m.pgn"]
STOCKFISH_PATH = PROJECT_DIR / "stockfish/stockfish-linux-x86-64-universal"
ENGINE_NODES = 100_000             # Work limit per search, not a fixed depth.
THREADS = 1
HASH_MB = 128
BLUNDER_CP = 200                   # Exactly 200 gives y=0; more than 200 gives y=1.


PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
                chess.ROOK: 500, chess.QUEEN: 900}


# 1. Move features: legal choices before the played move

# Which moves exist for the current at turn player (moves is a list we defined at the start)
def legal_move_count(board, moves):
    return len(moves)

# all legal captures including en passent
def capture_move_count(board, moves):
    return sum(board.is_capture(move) for move in moves)

# all legal checking moves
def checking_move_count(board, moves):
    return sum(board.gives_check(move) for move in moves)

# all legal checking + capturing moves
def checking_capture_count(board, moves):
    return sum(board.is_capture(move) and board.gives_check(move) for move in moves)

# all moves that neither capture nor give check
def quiet_move_count(board, moves):
    return sum(not board.is_capture(move) and not board.gives_check(move) for move in moves)

# all legal promoition choices (4 per pawn) but not all legal moves are promotions)
def promotion_move_count(board, moves):
    return sum(move.promotion is not None for move in moves)

# all legal castling moves
def castling_move_count(board, moves):
    return sum(board.is_castling(move) for move in moves)

MOVE_FEATURE_FUNCTIONS = [
    legal_move_count, capture_move_count, checking_move_count, checking_capture_count,
    quiet_move_count, promotion_move_count, castling_move_count,
]


def get_move_features(board):
    moves = list(board.legal_moves)
    result = {}
    for function in MOVE_FEATURE_FUNCTIONS:
        result[function.__name__] = function(board, moves)
    return result


# 2. Board features: pieces, pawn structure, attacks and king safety

# Calculate total material on the board for one color
def material(board, color, include_pawns=True):
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        if include_pawns or piece_type != chess.PAWN:
            total += len(board.pieces(piece_type, color)) * value
    return total

# doubled pawns are when two pawns of the same color are on one file
def doubled_pawns(board, color):
    # counter for each line (8total)
    counts = [0] * 8
    #returns positions of pawns 0-63 (squares)
    for square in board.pieces(chess.PAWN, color):
        counts[chess.square_file(square)] += 1
    # returns the higher of the count or 0 (because files with 0 pawns would be negative)
    return sum(max(0, count - 1) for count in counts)

#isolated pawns have no friendly pawn on an adjacent file
def isolated_pawns(board, color):
    pawns = list(board.pieces(chess.PAWN, color))
    files = {chess.square_file(square) for square in pawns}
    count = 0
    for square in pawns:
        file = chess.square_file(square)
        if file - 1 not in files and file + 1 not in files:
            count += 1
    return count

# passed pawns are pawns with no enemy pawn ahead on their file or an adjacent file
def passed_pawns(board, color):
    count = 0
    for square in board.pieces(chess.PAWN, color):
        blocked = False
        for enemy in board.pieces(chess.PAWN, not color):
            # must be 1 left right or on the same file then TRUE
            nearby_file = abs(chess.square_file(enemy) - chess.square_file(square)) <= 1
            #checks if the peace is ahead, or if it is "behind" if you are black
            ahead = chess.square_rank(enemy) > chess.square_rank(square) if color == chess.WHITE else chess.square_rank(enemy) < chess.square_rank(square)
            if nearby_file and ahead:
                blocked = True
                break
        if not blocked:
            count += 1
    return count

# a bishop pair is when a player has at least one bishop of each color
def bishop_pair(board, color):
    # a set only saves unique values, so if a player has a bishop on a light square and a bishop on a dark square, the set will have two values
    square_colors = set()
    for square in board.pieces(chess.BISHOP, color):
        # file + rank is even for one square color and odd for the other
        square_colors.add((chess.square_file(square) + chess.square_rank(square)) % 2)
        # if both colors are present i.e.  modulu 0 and 1 exist then the length of the set is 2 and  True gets returned int(true) is 1
    return int(len(square_colors) == 2)

# how many squares around a king are attacked by enemy pieces
def king_zone_attacks(board, color):
    # checks where the king is
    king = board.king(color)
    if king is None:
        return 0
    # Identifies all squares the king attacks (around it), converts that into a list of squares and adds the kings own square
    zone = list(chess.SquareSet(chess.BB_KING_ATTACKS[king])) + [king]
    # for each square in the zone, checks if it is attacked by an enemy piece and sums the total number of squares attacked
    return sum(board.is_attacked_by(not color, square) for square in zone)

# counts how many friendly pawns protect the king from the front (max 3) in one file
def pawn_shield(board, color):
    king = board.king(color)
    if king is None:
        return 0
    # front rank is the rank in front of the king, which is one rank higher for white and one rank lower for black
    front_rank = chess.square_rank(king) + (1 if color == chess.WHITE else -1)
    count = 0
    for square in board.pieces(chess.PAWN, color):
        # is the pawn in "front" of the king and is it exatcly max one file away from the king (left/right or same file)
        if chess.square_rank(square) == front_rank and abs(chess.square_file(square) - chess.square_file(king)) <= 1:
            count += 1
    return count

# list of all squares occupied by a player's pieces, excluding the king
def non_king_squares(board, color):
    return [square for square in chess.SquareSet(board.occupied_co[color])
            if board.piece_type_at(square) != chess.KING]

# number of pinned pieces
def pinned_pieces(board, color):
    return sum(board.is_pinned(color, square) for square in non_king_squares(board, color))

# number of non-king pieces attacked by at least one enemy piece
def attacked_pieces(board, color):
    """Count non-king pieces attacked geometrically by at least one enemy piece."""
    return sum(board.is_attacked_by(not color, square) for square in non_king_squares(board, color))

# list of pieces attacked by a enemy piece and not defended by a friendly piece
def hanging_squares(board, color):
    return [square for square in non_king_squares(board, color)
            if board.is_attacked_by(not color, square) and not board.is_attacked_by(color, square)]

# count number of rooks on files that have no pawns of either color
def rooks_on_open_files(board, color):
    white_pawns = list(board.pieces(chess.PAWN, chess.WHITE))
    black_pawns = list(board.pieces(chess.PAWN, chess.BLACK))
    all_pawns = white_pawns + black_pawns
    pawn_files = set()
    for square in all_pawns:
        pawn_files.add(chess.square_file(square))

    return sum(chess.square_file(square) not in pawn_files
               for square in board.pieces(chess.ROOK, color))

# are we in check 1/0
def in_check(board):
    return int(board.is_check())

# number of pieces giving check currently
def checker_count(board):
    return len(board.checkers())

# own material minus opponnent material using our values at the beginning
def material_balance_cp(board):
    return material(board, board.turn) - material(board, not board.turn)

# total material on the board excluding kings, using our values at the beginning
def total_material_cp(board):
    return material(board, chess.WHITE) + material(board, chess.BLACK)

# self-explanatory
def own_non_pawn_material_cp(board):
    return material(board, board.turn, include_pawns=False)

# ""
def opponent_non_pawn_material_cp(board):
    return material(board, not board.turn, include_pawns=False)

# m of own pawns
def own_pawn_count(board):
    return len(board.pieces(chess.PAWN, board.turn))

# "" opponents "
def opponent_pawn_count(board):
    return len(board.pieces(chess.PAWN, not board.turn))


def own_knight_count(board):
    return len(board.pieces(chess.KNIGHT, board.turn))


def opponent_knight_count(board):
    return len(board.pieces(chess.KNIGHT, not board.turn))


def own_bishop_count(board):
    return len(board.pieces(chess.BISHOP, board.turn))


def opponent_bishop_count(board):
    return len(board.pieces(chess.BISHOP, not board.turn))


def own_rook_count(board):
    return len(board.pieces(chess.ROOK, board.turn))


def opponent_rook_count(board):
    return len(board.pieces(chess.ROOK, not board.turn))


def own_queen_count(board):
    return len(board.pieces(chess.QUEEN, board.turn))


def opponent_queen_count(board):
    return len(board.pieces(chess.QUEEN, not board.turn))

# returns as pre-defined 1/0
def own_bishop_pair(board):
    return bishop_pair(board, board.turn)


def opponent_bishop_pair(board):
    return bishop_pair(board, not board.turn)


def own_doubled_pawn_count(board):
    return doubled_pawns(board, board.turn)


def opponent_doubled_pawn_count(board):
    return doubled_pawns(board, not board.turn)


def own_isolated_pawn_count(board):
    return isolated_pawns(board, board.turn)


def opponent_isolated_pawn_count(board):
    return isolated_pawns(board, not board.turn)


def own_passed_pawn_count(board):
    return passed_pawns(board, board.turn)


def opponent_passed_pawn_count(board):
    return passed_pawns(board, not board.turn)


def own_king_zone_attacked_count(board):
    return king_zone_attacks(board, board.turn)


def opponent_king_zone_attacked_count(board):
    return king_zone_attacks(board, not board.turn)


def own_pawn_shield_count(board):
    return pawn_shield(board, board.turn)


def opponent_pawn_shield_count(board):
    return pawn_shield(board, not board.turn)

# remaining castling rights (0, 1 or 2), but not if they are currently legal
def own_castling_rights_count(board):
    return int(board.has_kingside_castling_rights(board.turn)) + int(board.has_queenside_castling_rights(board.turn))


def opponent_castling_rights_count(board):
    return int(board.has_kingside_castling_rights(not board.turn)) + int(board.has_queenside_castling_rights(not board.turn))


def own_pinned_piece_count(board):
    return pinned_pieces(board, board.turn)


def opponent_pinned_piece_count(board):
    return pinned_pieces(board, not board.turn)


def own_attacked_piece_count(board):
    return attacked_pieces(board, board.turn)


def opponent_attacked_piece_count(board):
    return attacked_pieces(board, not board.turn)


def own_hanging_piece_count(board):
    return len(hanging_squares(board, board.turn))


def opponent_hanging_piece_count(board):
    return len(hanging_squares(board, not board.turn))


def own_hanging_material_cp(board):
    return sum(PIECE_VALUES[board.piece_type_at(square)] for square in hanging_squares(board, board.turn))


def opponent_hanging_material_cp(board):
    return sum(PIECE_VALUES[board.piece_type_at(square)] for square in hanging_squares(board, not board.turn))


def own_rooks_on_open_files_count(board):
    return rooks_on_open_files(board, board.turn)


def opponent_rooks_on_open_files_count(board):
    return rooks_on_open_files(board, not board.turn)


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

def get_board_features(board):
    result = {}
    for function in BOARD_FEATURE_FUNCTIONS:
        result[function.__name__] = function(board)
    return result


# 3. Game features: ratings and time control

def mover_elo(headers, player):
    value = headers.get("WhiteElo" if player == chess.WHITE else "BlackElo")
    return int(value) if value is not None and value.isdigit() else None


def opponent_elo(headers, player):
    return mover_elo(headers, not player)


def rating_difference(headers, player):
    own = mover_elo(headers, player)
    opponent = opponent_elo(headers, player)
    if own is None or opponent is None:
        return None
    return own - opponent


# player is unused here, but all game functions accept the same arguments.
def initial_seconds(headers, player=None):
    return int(headers["TimeControl"].split("+")[0])


GAME_FEATURE_FUNCTIONS = [mover_elo, opponent_elo, rating_difference, initial_seconds]


def get_game_features(headers, player):
    result = {}
    for function in GAME_FEATURE_FUNCTIONS:
        result[function.__name__] = function(headers, player)
    return result


# 4. Clock features: time left, last move time, and derived features

def time_left_seconds(clocks, last_spent, player, initial):
    return clocks[player]


def opponent_time_left_seconds(clocks, last_spent, player, initial):
    return clocks[not player]


def time_left_fraction(clocks, last_spent, player, initial):
    seconds = clocks[player]
    if seconds is None or initial <= 0:
        return None
    return seconds / initial


def clock_difference(clocks, last_spent, player, initial):
    seconds = clocks[player]
    opponent_seconds = clocks[not player]
    if seconds is None or opponent_seconds is None:
        return None
    return seconds - opponent_seconds


def time_left_log1p(clocks, last_spent, player, initial):
    seconds = clocks[player]
    if seconds is None or seconds < 0:
        return None
    return math.log1p(seconds)  # ln(1 + seconds), so zero is okay.


def low_time_10s(clocks, last_spent, player, initial):
    seconds = clocks[player]
    return int(seconds <= 10) if seconds is not None else None


def last_move_seconds(clocks, last_spent, player, initial):
    return last_spent[player]


CLOCK_FEATURE_FUNCTIONS = [
    time_left_seconds, opponent_time_left_seconds, time_left_fraction, clock_difference,
    time_left_log1p, low_time_10s, last_move_seconds,
]


def get_clock_features(clocks, last_spent, player, initial):
    result = {}
    for function in CLOCK_FEATURE_FUNCTIONS:
        result[function.__name__] = function(clocks, last_spent, player, initial)
    return result


# 5. Move number

def move_number(board):
    return board.fullmove_number


MOVE_NUMBER_FEATURE_FUNCTIONS = [move_number]


def get_move_number_features(board):
    result = {}
    for function in MOVE_NUMBER_FEATURE_FUNCTIONS:
        result[function.__name__] = function(board)
    return result


# Collect the five groups, stockfish values are added later in the main loop
def get_all_features(headers, board, clocks, last_spent):
    result = {}
    result.update(get_move_features(board))
    result.update(get_board_features(board))
    result.update(get_game_features(headers, board.turn))
    result.update(get_clock_features(clocks, last_spent, board.turn, result["initial_seconds"]))
    result.update(get_move_number_features(board))
    return result


# 6. Stockfish analysis and the label

def analyse_position(engine, board, root_moves=None):
    if not any(board.legal_moves):
        return None
    analysis = None
    exact = None
    total_nodes = None
    # Ask Stockfish to analyse the position.
    with engine.analysis(board, chess.engine.Limit(nodes=ENGINE_NODES), game=object(), root_moves=root_moves) as search:
        # Stockfish sends updated info until the search finishes.
        for info in search:
            # Record the total number of searched nodes.
            if "nodes" in info:
                total_nodes = info["nodes"]
            # PV is the preferred sequence of moves; keep it together with its score.
            if "score" in info and info.get("pv"):
                analysis = info.copy()
                if not info.get("lowerbound") and not info.get("upperbound"):
                    exact = info.copy()
    # A node limit can stop an iteration halfway. We keep the last complete score
    if exact is not None:
        analysis = exact
    if analysis is not None:
        analysis["nodes"] = total_nodes
    return analysis


def pre_move_cp(analysis, player):
    if analysis is None or "score" not in analysis:
        return None
    if analysis.get("lowerbound") or analysis.get("upperbound"):
        return None
    return analysis["score"].pov(player).score()  # None for mate scores.


# check for a forced mate and contextualize it
def check_for_mate(analysis, player):
    # does an analysis exist?
    if analysis is None or "score" not in analysis:
        return None, "missing_evaluation"
    # .mate checks for a mate, stockfish would've labeled a mate
    score = analysis["score"].pov(player)
    mate = score.mate()
    # if the score is bounded we label it as such, return the mate (which may be a mate e.g. at least as favorable as a mate in 3) or none if stockfish didnt find a mate, similar to the pre_move_cp function
    if analysis.get("lowerbound") or analysis.get("upperbound"):
        return mate, "bounded_score"
    # if there is no mate we label it.
    if mate is None:
        return None, "finite_cp"
    # check if we having a winning or losing mate
    if score > chess.engine.Cp(0):
        return mate, "winning_mate"
    return mate, "losing_mate"

# inputs: best evaluation, evaluation of the played move and both their statusses (missing, bounded, finite, winning mate, losing mate)
def move_target(best_cp, played_cp, best_status, played_status):
    # the nominal loss in cp, the label y (yes or no>200cp loss/missed mate) and the move classification/status
    result = {"eval_loss_cp": None, "y": None, "label_status": "missing_evaluation"}
    # check for missing results
    if best_status == "missing_evaluation" or played_status == "missing_evaluation":
        return result
    # check for bounded results, because we dont know the exact score we cannot calculate a loss
    if best_status == "bounded_score" or played_status == "bounded_score":
        result["label_status"] = "bounded_score"
        return result
    # check for finite cp results
    if best_status == "finite_cp" and played_status == "finite_cp":
        if best_cp is not None and played_cp is not None:
            # define loss
            loss = best_cp - played_cp
            # for for a loss of more than 200 cp we update our result dictionary with the nominal cp loss, label y (1 for yes, 0 for no) and the label status
            result.update(eval_loss_cp=loss, y=int(loss > BLUNDER_CP), label_status="finite_cp")
        return result

    #possible checkmate cases
    #check for discrepencies between winning mate and actual played move
    if best_status == "winning_mate":
        if played_status == "winning_mate":
            result.update(y=0, label_status="winning_mate_retained")
        else:
            result.update(y=1, label_status="missed_forced_win")
    # check for discrepencies between losing mate and actual played move
    elif best_status == "losing_mate":
        if played_status == "losing_mate":
            result.update(y=0, label_status="already_forced_loss")
        # a losing mate is by definition losing whatever we do, so if the played move is not a losing mate we have an issue with mate evaluation
        else:
            result["label_status"] = "inconsistent_mate_evaluations"

    elif best_status != "losing_mate" and played_status == "losing_mate":
        result.update(y=1, label_status="allowed_forced_loss")
    # check for a winning mate that was played but not found by stockfish in the intial search but the subsequent one found it
    elif played_status == "winning_mate":
        result.update(y=0, label_status="winning_mate_played")
    return result


# Column groups follow the same order as the feature sections above.
MOVE_COLUMNS = []
for function in MOVE_FEATURE_FUNCTIONS:
    MOVE_COLUMNS.append(function.__name__)

BOARD_COLUMNS = []
for function in BOARD_FEATURE_FUNCTIONS:
    BOARD_COLUMNS.append(function.__name__)

GAME_COLUMNS = []
for function in GAME_FEATURE_FUNCTIONS:
    GAME_COLUMNS.append(function.__name__)

CLOCK_COLUMNS = []
for function in CLOCK_FEATURE_FUNCTIONS:
    CLOCK_COLUMNS.append(function.__name__)

NUMBER_COLUMNS = []
for function in MOVE_NUMBER_FEATURE_FUNCTIONS:
    NUMBER_COLUMNS.append(function.__name__)

PREDICTOR_COLUMNS = (MOVE_COLUMNS + BOARD_COLUMNS + GAME_COLUMNS + CLOCK_COLUMNS
                     + NUMBER_COLUMNS + ["pre_eval_cp"])

TARGET_COLUMNS = ["y"]
# this is context we get from the PGN and the Stockfish analysis, but is not used as a predictor for the model, ive kept it as it helps to understand the data
METADATA_COLUMNS = [
    "game_id", "ply", "fen", "white_elo", "black_elo",
    "player_to_move", "time_control", "utc_date", "utc_time",
    "source_pgn", "played_move", "engine_best_move",
    "before_eval_depth", "played_eval_depth",
    "before_eval_nodes", "played_eval_nodes",
    "best_eval_status", "played_eval_status",
    "played_eval_cp", "pre_mate", "played_mate",
    "eval_loss_cp", "label_status", "pgn_error"
]

CSV_COLUMNS = TARGET_COLUMNS + PREDICTOR_COLUMNS + [" "] + METADATA_COLUMNS


def process_pgn(pgn_path, csv_path, engine):
    with pgn_path.open(encoding="utf-8") as source, csv_path.open("x", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        games = 0

        while True:
            game = chess.pgn.read_game(source)
            if game is None:
                break

            # Record broken games and continue with the next game.
            if game.errors:
                writer.writerow({
                    "game_id": game.headers.get("Site", "").rstrip("/").split("/")[-1],
                    "source_pgn": pgn_path.name,
                    "label_status": "pgn_error",
                    "pgn_error": str(game.errors[0])
                })
                continue

            games += 1
            print(f"{pgn_path.name}: game {games}", flush=True)

            # Metadata that stays the same throughout the game.
            game_metadata = {
                "game_id": game.headers.get("Site", "").rstrip("/").split("/")[-1],
                "white_elo": game.headers.get("WhiteElo"),
                "black_elo": game.headers.get("BlackElo"),
                "time_control": game.headers.get("TimeControl"),
                "utc_date": game.headers.get("UTCDate"),
                "utc_time": game.headers.get("UTCTime"),
                "source_pgn": pgn_path.name
            }

            board = game.board()
            clocks = {chess.WHITE: None, chess.BLACK: None}
            last_spent = {chess.WHITE: None, chess.BLACK: None}

            for ply, node in enumerate(game.mainline(), start=1):
                player = board.turn

                # Copy game metadata and calculate pre-move predictors.
                row = game_metadata.copy()
                row.update(get_all_features(game.headers, board, clocks, last_spent))

                # Metadata that changes with each move.
                row["ply"] = ply
                row["fen"] = board.fen()
                row["player_to_move"] = "white" if player == chess.WHITE else "black"
                row["played_move"] = node.move.uci()

                # Evaluate the best move and the player's actual move.
                best_eval = analyse_position(engine, board)

                if best_eval is not None and node.move == best_eval["pv"][0]:
                    played_eval = best_eval
                else:
                    played_eval = analyse_position(engine, board, root_moves=[node.move])

                # Extract centipawn evaluations and mate information.
                best_cp = pre_move_cp(best_eval, player)
                played_cp = pre_move_cp(played_eval, player)
                best_mate, best_status = check_for_mate(best_eval, player)
                played_mate, played_status = check_for_mate(played_eval, player)

                # Calculate the target and save evaluation information.
                evaluation_values = move_target(best_cp, played_cp, best_status, played_status)
                evaluation_values["pre_eval_cp"] = best_cp
                evaluation_values["played_eval_cp"] = played_cp
                evaluation_values["pre_mate"] = best_mate
                evaluation_values["played_mate"] = played_mate
                row.update(evaluation_values)

                # Stockfish metadata for this move.
                stockfish_metadata = {
                    "engine_best_move": best_eval["pv"][0].uci() if best_eval is not None else None,
                    "before_eval_depth": best_eval.get("depth") if best_eval is not None else None,
                    "played_eval_depth": played_eval.get("depth") if played_eval is not None else None,
                    "before_eval_nodes": best_eval.get("nodes") if best_eval is not None else None,
                    "played_eval_nodes": played_eval.get("nodes") if played_eval is not None else None,
                    "best_eval_status": best_status,
                    "played_eval_status": played_status
                }
                row.update(stockfish_metadata)

                # Save the completed row.
                writer.writerow(row)

                # Advance the board and update clock information.
                board.push(node.move)
                current = node.clock()
                previous = clocks[player]

                last_spent[player] = None
                if previous is not None and current is not None:
                    last_spent[player] = previous - current

                clocks[player] = current

                if ply % 50 == 0:
                    target.flush()
                    print(f"  ply {ply}", flush=True)

            target.flush()

    print(f"Finished {csv_path.name}", flush=True)

# context for buncha bull that chatgpt made sense for recordkeeping
def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    with chess.engine.SimpleEngine.popen_uci(str(STOCKFISH_PATH)) as engine:
        engine.configure({"Threads": THREADS, "Hash": HASH_MB, "SyzygyPath": ""})
        print(f"Using {engine.id['name']}", flush=True)
        protocol = {"engine": engine.id, "engine_path": str(STOCKFISH_PATH),
                    "python_chess_version": chess.__version__, "nodes_per_search": ENGINE_NODES,
                    "threads": THREADS, "hash_mb": HASH_MB, "multipv": 1, "tablebases": False,
                    "fresh_search_state": True, "score": "Last unbounded score/PV; total search nodes recorded",
                    "target": f"Strictly >{BLUNDER_CP}cp loss, or missed winning mate/new losing mate",
                    "mate_distance_changes": "Ignored; inconsistent losing-mate searches stay unclassified",
                    "predictor_columns": PREDICTOR_COLUMNS, "target_columns": TARGET_COLUMNS}
        with (OUTPUT_DIR / "engine_protocol.json").open("x", encoding="utf-8") as output:
            json.dump(protocol, output, indent=2)
        for filename in PGN_FILES:
            pgn_path = DATA_DIR / filename
            csv_path = OUTPUT_DIR / (pgn_path.stem + ".csv")
            process_pgn(pgn_path, csv_path, engine)
    print(f"Finished all three files: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    run()
