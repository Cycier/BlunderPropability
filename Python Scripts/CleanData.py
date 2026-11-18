# Clean collected rows; no splitting, imputation or modeling here.
import csv
import json
import math
from pathlib import Path

from Complexity import CSV_COLUMNS, PREDICTOR_COLUMNS, get_clock_features

PROJECT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_DIR / 'data/positions_20261118'
OUTPUT_DIR = PROJECT_DIR / 'data/cleaned_20261118'
FILES = ['games_1m.csv', 'games_5m.csv', 'games_10m.csv']


def numeric(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def clean_file(source_path, output_path):
    columns = []
    for name in CSV_COLUMNS:
        if name != ' ':
            columns.append(name)
    columns.append('pre_eval_cp_missing')
    counts = {'read': 0, 'kept': 0, 'pgn_errors': 0, 'unlabeled': 0,
              'invalid_id': 0, 'duplicates': 0, 'clock_rows_masked': 0,
              'missing_pre_eval_kept': 0, 'blunders_kept': 0}
    seen = set()
    current_game = None
    previous_clocks = {True: None, False: None}
    bad_clocks = set()

    with source_path.open(encoding='utf-8') as source, output_path.open('x', newline='', encoding='utf-8') as output:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in reader:
            counts['read'] += 1
            if row['label_status'] == 'pgn_error':
                counts['pgn_errors'] += 1
                continue
            game_id = row['game_id']
            if not game_id or not row['ply'].isdigit() or row['player_to_move'] not in ['white', 'black']:
                counts['invalid_id'] += 1
                continue
            key = (game_id, int(row['ply']))
            if key in seen:
                counts['duplicates'] += 1
                continue
            seen.add(key)
            if game_id != current_game:
                current_game = game_id
                previous_clocks = {True: None, False: None}
                bad_clocks = set()

            for name in PREDICTOR_COLUMNS:
                row[name] = numeric(row[name])
            player = row['player_to_move'] == 'white'
            initial = row['initial_seconds']
            clocks = {player: row['time_left_seconds'], not player: row['opponent_time_left_seconds']}

            # Read history even on rows with no label, before deciding whether to keep them.
            for color in [player, not player]:
                seconds = clocks[color]
                previous = previous_clocks[color]
                if seconds is not None:
                    if (seconds < 0 or initial is None or seconds > initial
                            or (previous is not None and seconds > previous)):
                        bad_clocks.add(color)
                    # Keep the last known clock when an annotation is missing.
                    previous_clocks[color] = seconds
                if color in bad_clocks:
                    clocks[color] = None
            spent = row['last_move_seconds']
            if spent is not None and spent < 0:
                bad_clocks.add(player)
                clocks[player] = None
            if player in bad_clocks:
                spent = None
            clock_features = get_clock_features(clocks, {player: spent, not player: None}, player,
                                                initial if initial is not None else 0)
            clock_changed = (clock_features['time_left_seconds'] != row['time_left_seconds']
                             or clock_features['opponent_time_left_seconds'] != row['opponent_time_left_seconds']
                             or spent != row['last_move_seconds'])
            row.update(clock_features)

            if row['y'] not in ['0', '1']:
                counts['unlabeled'] += 1
                continue
            row['pre_eval_cp_missing'] = int(row['pre_eval_cp'] is None)
            row.pop(' ', None)
            writer.writerow(row)
            counts['kept'] += 1
            counts['blunders_kept'] += int(row['y'] == '1')
            counts['clock_rows_masked'] += int(clock_changed)
            counts['missing_pre_eval_kept'] += row['pre_eval_cp_missing']
    return counts


def run(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {'files': {}, 'predictor_columns': PREDICTOR_COLUMNS + ['pre_eval_cp_missing'],
              'notes': ['Mate-labeled rows are retained; missing pre_eval_cp stays missing.',
                        'Clock anomalies affect only current and later available clock values.',
                        'Fit imputation and scaling inside training folds, not here.']}
    for filename in FILES:
        counts = clean_file(input_dir / filename, output_dir / filename)
        report['files'][filename] = counts
        print(f"{filename}: kept {counts['kept']} of {counts['read']} rows")
    with (output_dir / 'cleaning_report.json').open('x', encoding='utf-8') as output:
        json.dump(report, output, indent=2)
    return report


if __name__ == '__main__':
    run()
