# 1. Imports and editable settings
# csv writes tables; time measures runtime; Path handles folders and filenames.
import csv
import time
from pathlib import Path

# python-chess reads PGNs, reconstructs boards and communicates with Stockfish.
import chess
import chess.pgn
import chess.engine

# This script lives in "Python Scripts", one folder below the project folder.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data/results"
OUTPUT_DIR = PROJECT_DIR / "data" / time.strftime("position_dataset_%Y%m%d_%H%M%S")
STOCKFISH_PATH = Path("/home/jan/.local/share/org.encroissant.app/engines/stockfish/stockfish-linux-x86-64-universal")
PGN_FILES = ["games_1m.pgn", "games_5m.pgn", "games_10m.pgn"]

# Start with the FIRST game in each file, including every played move.
# This is a runtime test, not a new random sample. None processes all games.
GAMES_PER_FILE = 1
ENGINE_DEPTH = 8               # Pilot depth. Check stronger depths before a final run.
THREADS = 1                    # One CPU thread keeps the engine protocol consistent.
HASH_MB = 128                  # Memory used for Stockfish's search table.
GOOD_MOVE_CP = 50              # A good move scores within 50 cp of the best move.
BLUNDER_CP = 200               # y = 1 only if the played move loses MORE than 200 cp.
PROGRESS_EVERY = 10            # Print progress after this many position rows.

# A hand-written material count, separate from Stockfish's position evaluation.
PIECE_VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
                chess.ROOK: 500, chess.QUEEN: 900}


# 2. Count the simple features on the board BEFORE the player moves
def board_features(board):
    legal_moves = list(board.legal_moves)
    captures = 0
    checks = 0
    for move in legal_moves:
        captures += int(board.is_capture(move))
        checks += int(board.gives_check(move))

    own_material = 0
    opponent_material = 0
    for piece, value in PIECE_VALUES.items():
        own_material += len(board.pieces(piece, board.turn)) * value
        opponent_material += len(board.pieces(piece, not board.turn)) * value

    return {"legal_moves": len(legal_moves), "captures": captures, "checks": checks,
            "in_check": board.is_check(), "material_balance_cp": own_material - opponent_material}


# 3. Evaluate all legal moves, then keep only the position's summary measurements
def analyse_position(engine, board):
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        raise ValueError("No legal moves: this is not a position where a player can choose a move.")

    # MultiPV asks for several candidate moves. Here we request ALL legal moves.
    # A fixed depth avoids stopping halfway through a comparison because time ran out.
    # game=object() gives each position a fresh search state, with no old cached search.
    infos = engine.analyse(board, chess.engine.Limit(depth=ENGINE_DEPTH),
                           multipv=len(legal_moves), game=object())
    # The library's Score objects distinguish ordinary cp scores from mate scores.
    # Keep scores only for this position; do not write a row for every legal move.
    scores = {}
    for info in infos:
        move = info["pv"][0]  # First move of the engine's suggested continuation.
        scores[move] = info["score"].pov(board.turn)  # Positive is better for the CURRENT player.

    # Checking the actual moves catches missing or duplicate candidates, not just wrong counts.
    if len(infos) != len(legal_moves) or set(scores) != set(legal_moves):
        raise ValueError("Stockfish did not return exactly one evaluation for every legal move.")
    result = {"best_score_cp": None, "good_move_count": None, "bad_move_count": None,
              "best_second_gap_cp": None, "evaluation_status": "ok"}

    # Initially leave cp-based measurements blank if ANY candidate has a mate score.
    # Do not replace mate with an arbitrary large number, or label these cases as y=0.
    if any(score.is_mate() for score in scores.values()):
        result["evaluation_status"] = "mate_score"
    elif any(info.get("lowerbound") or info.get("upperbound") for info in infos):
        result["evaluation_status"] = "score_bound"
    elif any(info.get("depth") != ENGINE_DEPTH for info in infos):
        result["evaluation_status"] = "incomplete_depth"
    else:
        cp_scores = sorted([score.score() for score in scores.values()], reverse=True)
        best = cp_scores[0]
        result["best_score_cp"] = best
        # Includes the best move itself. Captures/checks and this count are separate features.
        result["good_move_count"] = sum(best - score <= GOOD_MOVE_CP for score in cp_scores)
        result["bad_move_count"] = sum(best - score > BLUNDER_CP for score in cp_scores)
        if len(cp_scores) > 1:
            result["best_second_gap_cp"] = best - cp_scores[1]

    # With one legal move there is one choice, and no second-best gap, even in a mate case.
    if len(scores) == 1:
        result["good_move_count"] = 1
    return scores, result


# 4. Calculate the TARGET separately. These columns must NEVER be predictors.
def move_target(scores, played_move, best_score_cp):
    played = scores[played_move]
    result = {"played_move": played_move.uci(), "played_score_cp": played.score(),
              "played_mate_in_moves": played.mate(), "cp_loss": None, "y": None}
    if best_score_cp is not None:
        result["cp_loss"] = best_score_cp - played.score()
        result["y"] = int(result["cp_loss"] > BLUNDER_CP)
    return result


# 5. Walk through one game and write one row BEFORE each recorded move
def analyse_game(game, engine, position_writer):
    headers = game.headers
    if headers.get("Variant", "Standard") != "Standard" or "FEN" in headers:
        raise ValueError("Expected a standard game from the normal starting position.")
    if headers.get("TimeControl") not in {"60+0", "300+0", "600+0"}:
        raise ValueError("This script handles only the three collected zero-increment controls.")
    game_id = headers["Site"].rstrip("/").split("/")[-1]
    initial_seconds = int(headers["TimeControl"].split("+")[0])
    board = game.board()  # Keep the full move history, including possible repetitions.
    previous_clock = {chess.WHITE: None, chess.BLACK: None}
    moves_seen = {chess.WHITE: 0, chess.BLACK: 0}
    clock_problem = {chess.WHITE: False, chess.BLACK: False}
    rows = 0

    for ply, node in enumerate(game.mainline(), start=1):
        player = board.turn
        previous = previous_clock[player]
        if moves_seen[player] == 0:
            clock_status = "first_move_unknown"  # Nominal starting time may be wrong for berserk.
        elif clock_problem[player]:
            clock_status = "prior_clock_anomaly"
        elif previous is None:
            clock_status = "missing_previous_annotation"
        else:
            clock_status = "previous_own_annotation_estimate"
        time_left = previous if clock_status == "previous_own_annotation_estimate" else None

        # All predictors below describe the position and information BEFORE this move.
        row = {"game_id": game_id, "ply": ply, "fen": board.fen(),
               "white_elo": int(headers["WhiteElo"]), "black_elo": int(headers["BlackElo"]),
               "player_to_move": "white" if player == chess.WHITE else "black",
               "time_control": headers["TimeControl"], "initial_seconds": initial_seconds,
               "time_left_seconds": time_left, "clock_status": clock_status}
        row.update(board_features(board))
        scores, measurements = analyse_position(engine, board)
        row.update(measurements)

        # Only this step looks up what the human actually played: outcome information.
        row.update(move_target(scores, node.move, row["best_score_cp"]))
        position_writer.writerow(row)
        rows += 1
        if rows % PROGRESS_EVERY == 0:
            print(f"  Game {game_id}: saved {rows} positions", flush=True)

        # Read the CURRENT after-move clock only AFTER forming this move's row.
        # A known anomaly makes later clock estimates missing for this player.
        current = node.clock()
        if current is not None:
            if current < 0 or current > initial_seconds or (previous is not None and current > previous):
                clock_problem[player] = True
        previous_clock[player] = current  # Missing annotation stays missing, not an older clock.
        moves_seen[player] += 1
        board.push(node.move)             # Advance to the position for the next player's turn.
    return rows


# 6. Open the engine once, loop over the three PGNs and save one position table
def run():
    if ENGINE_DEPTH < 1 or (GAMES_PER_FILE is not None and GAMES_PER_FILE < 1):
        raise ValueError("Use a positive depth and positive games per file (or None for all games).")
    for path in [STOCKFISH_PATH] + [DATA_DIR / name for name in PGN_FILES]:
        if not path.is_file():
            raise FileNotFoundError(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)  # Refuse existing folders; never overwrite data.
    started = time.time()
    total_games = 0
    total_positions = 0
    notes = OUTPUT_DIR / "run_info.txt"
    notes.write_text(f"Status: started\nInput: {DATA_DIR}\nEngine: {STOCKFISH_PATH}\n"
                     f"Depth: {ENGINE_DEPTH}; threads: {THREADS}; hash: {HASH_MB} MiB; MultiPV: ALL legal moves\n"
                     f"First games per file: {GAMES_PER_FILE}; all played plies per game\n"
                     f"Good moves include best, loss <= {GOOD_MOVE_CP} cp; y = loss > {BLUNDER_CP} cp\n"
                     "bad_move_count counts ALL legal choices losing more than the blunder threshold\n"
                     "Only positions.csv is saved; legal-move scores are temporary, one position at a time\n"
                     "Scores: current mover's perspective; fresh search state per position\n"
                     "Mate/bound/incomplete evaluations: cp-derived measurements and y blank; one legal move still has count 1\n"
                     "Partial CSVs from a failed/interrupted run are not a completed dataset.\n")

    # Explicit column lists make the dataset's structure easy to inspect and import.
    position_fields = ["game_id", "ply", "fen", "white_elo", "black_elo", "player_to_move",
                       "time_control", "initial_seconds", "time_left_seconds", "clock_status",
                       "legal_moves", "captures", "checks", "in_check", "material_balance_cp",
                       "best_score_cp", "good_move_count", "bad_move_count", "best_second_gap_cp", "evaluation_status",
                       "played_move", "played_score_cp", "played_mate_in_moves", "cp_loss", "y"]
    try:
        with chess.engine.SimpleEngine.popen_uci(str(STOCKFISH_PATH), timeout=120) as engine:
            engine.configure({"Threads": THREADS, "Hash": HASH_MB, "UCI_LimitStrength": False,
                              "Skill Level": 20, "SyzygyPath": ""})
            with notes.open("a") as f:
                f.write(f"Engine version: {engine.id['name']}\n")
            print(f"{engine.id['name']}: depth {ENGINE_DEPTH}, ALL legal moves; output {OUTPUT_DIR}", flush=True)
            with (OUTPUT_DIR / "positions.csv").open("x", newline="", encoding="utf-8") as positions:
                position_writer = csv.DictWriter(positions, fieldnames=position_fields)
                position_writer.writeheader()
                for filename in PGN_FILES:
                    games_in_file = 0
                    with (DATA_DIR / filename).open(encoding="utf-8") as pgn:
                        while GAMES_PER_FILE is None or games_in_file < GAMES_PER_FILE:
                            game = chess.pgn.read_game(pgn)
                            if game is None:
                                break
                            if game.errors:
                                raise ValueError(f"Invalid PGN in {filename}: {game.errors}")
                            count = analyse_game(game, engine, position_writer)
                            positions.flush()
                            games_in_file += 1
                            total_games += 1
                            total_positions += count
                            print(f"{filename}: game {games_in_file}, {count} positions; "
                                  f"total {total_positions} in {time.time() - started:.1f}s", flush=True)
            if total_positions == 0:
                raise ValueError("No positions found in the selected PGNs.")
            engine.quit()
    except (Exception, KeyboardInterrupt) as error:
        with notes.open("a") as f:
            f.write(f"Status: FAILED — {type(error).__name__}: {error}\n")
        raise
    elapsed = time.time() - started
    with notes.open("a") as f:
        f.write(f"Status: COMPLETED\nGames: {total_games}; positions: {total_positions}\n"
                f"Elapsed: {elapsed:.1f}s; seconds per position: {elapsed / total_positions:.3f}\n")
    print(f"Finished: {total_games} games, {total_positions} positions in {elapsed:.1f}s", flush=True)


# Importing this file does not run the analysis. Running it as a script does.
if __name__ == "__main__":
    run()
