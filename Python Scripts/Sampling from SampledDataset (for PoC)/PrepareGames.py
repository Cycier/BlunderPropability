# Select whole games before analysis; Complexity.py still processes every input move.
import csv
import json
import random
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data/results'
PILOT_MANIFEST = PROJECT_DIR / 'data/pilot_20261117/pilot_selection.json'
OUTPUT_DIR = PROJECT_DIR / 'data/run_input_20261118'
GAMES_PER_CONTROL = 275             # About 9 hours at the measured pilot speed, with headroom.
SEED = 20261118
FILES = ['games_1m.pgn', 'games_5m.pgn', 'games_10m.pgn']


def read_games(source):
    lines = []
    for line in source:
        if line.startswith('[Event "') and lines:
            yield ''.join(lines)
            lines = []
        lines.append(line)
    if lines:
        yield ''.join(lines)


def run(games_per_control=GAMES_PER_CONTROL, output_dir=OUTPUT_DIR):
    output_dir = Path(output_dir)
    excluded = set()
    with PILOT_MANIFEST.open() as source:
        pilot = json.load(source)
    for file in pilot['files']:
        for game in file['selected']:
            excluded.add(game['game_id'])
    pools = {name: [] for name in FILES}
    with (DATA_DIR / 'games_metadata.csv').open() as source:
        for row in csv.DictReader(source):
            if row['game_id'] not in excluded:
                pools[row['pgn_file']].append(row)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {'seed': SEED, 'games_per_control': games_per_control,
                'sampling': 'Uniform whole games within each available time-control file; no label-based selection',
                'source_scope': 'Available early-October prefix, not a whole-month sample',
                'pilot_games_excluded': sorted(excluded), 'files': [], 'expected_positions': 0}
    for index, name in enumerate(FILES):
        selected = random.Random(SEED + index).sample(pools[name], games_per_control)
        selected_ids = {row['game_id'] for row in selected}
        found = set()
        with (DATA_DIR / name).open() as source, (output_dir / name).open('x') as output:
            for text in read_games(source):
                match = re.search(r'\[Site "([^"]+)"\]', text)
                game_id = match.group(1).rstrip('/').split('/')[-1]
                if game_id in selected_ids:
                    output.write(text.rstrip() + '\n\n')
                    found.add(game_id)
        assert found == selected_ids, f'Some selected games were not found in {name}'
        positions = sum(int(row['plies']) for row in selected)
        manifest['files'].append({'filename': name, 'games': len(selected), 'positions': positions,
                                  'selected': [{'game_id': row['game_id'], 'plies': int(row['plies'])} for row in selected]})
        manifest['expected_positions'] += positions
        print(f'{name}: {len(selected)} games, {positions} expected positions')
    with (output_dir / 'selection_manifest.json').open('x') as output:
        json.dump(manifest, output, indent=2)
    return manifest


if __name__ == '__main__':
    run()
