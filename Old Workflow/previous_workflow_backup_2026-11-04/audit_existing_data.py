"""Read-only full header audit and seeded semantic sample of the original data."""
import csv
import importlib.util
import json
import logging
import random
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lichess_collector', HERE / '02_lichess_stratified_sample.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
logging.getLogger('chess.pgn').setLevel(logging.CRITICAL)
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, default=HERE / 'data/lichess_2026-10_balanced')
source = parser.parse_args().source
metadata = {}
metadata_duplicate_ids = Counter()
with (source / 'games_metadata.csv').open(newline='') as f:
    for row in csv.DictReader(f):
        gid = row['game_id']
        if gid in metadata:
            metadata_duplicate_ids[gid] += 1
        metadata[gid] = row

started = time.perf_counter()
counts, header_rejects, dates, mismatches, per_control, clock_counts = (Counter() for _ in range(6))
ids = set()
samples = {tc: [] for tc in collector.CONTROLS}
rngs = {tc: random.Random(2026 + int(tc.split('+')[0])) for tc in collector.CONTROLS}
for tc, label in collector.CONTROLS.items():
    with (source / f'games_{label}.pgn').open() as f:
        for i, raw in enumerate(collector.raw_games(f), 1):
            h = collector.read_tags(raw)
            counts['raw_games'] += 1
            reason = collector.header_check(h, '2026-10')
            if reason:
                header_rejects[reason] += 1
            gid_match = collector.SITE_RE.fullmatch(h.get('Site', ''))
            gid = gid_match[1] if gid_match else ''
            if gid in ids:
                counts['duplicate_pgn_ids'] += 1
            ids.add(gid)
            dates[h.get('UTCDate', '')] += 1
            per_control[h.get('TimeControl', '')] += 1
            clocks = raw.count('[%clk ')
            clock_counts[tc] += clocks
            row = metadata.get(gid)
            if row is None:
                mismatches['pgn_id_missing_from_metadata'] += 1
            else:
                for old, tag in [('date','UTCDate'), ('time_control','TimeControl'), ('white_elo','WhiteElo'), ('black_elo','BlackElo'), ('result','Result')]:
                    if row[old] != h.get(tag):
                        mismatches[old] += 1
                if int(row['clock_annotations']) != clocks:
                    mismatches['clock_count'] += 1
            if tc != h.get('TimeControl'):
                mismatches['wrong_pgn_file'] += 1
            if len(samples[tc]) < 100:
                samples[tc].append(raw)
            else:
                j = rngs[tc].randrange(i)
                if j < 100:
                    samples[tc][j] = raw
header_seconds = time.perf_counter() - started
print(f'Full header audit: {counts["raw_games"]:,} games in {header_seconds:.2f}s', flush=True)

sample_counts, sample_rejects, sample_flags, sample_plies = (Counter() for _ in range(4))
sample_ids = {}
semantic_started = time.perf_counter()
for tc, raws in samples.items():
    selected_ids = []
    for raw in raws:
        h = collector.read_tags(raw)
        selected_ids.append(collector.SITE_RE.fullmatch(h['Site'])[1])
        meta, reason = collector.validate_game(raw, h, '2026-10')
        sample_counts['checked_games'] += 1
        if reason:
            sample_rejects[reason] += 1
        else:
            sample_counts['valid_games'] += 1
            sample_plies[tc] += meta['plies']
            for flag in ['first_clock_below_nominal', 'suspected_berserk']:
                if meta[flag]:
                    sample_flags[flag] += 1
            if meta['clock_increases']:
                sample_flags['games_with_clock_increases'] += 1
                sample_flags['clock_increases'] += meta['clock_increases']
    sample_ids[tc] = selected_ids
semantic_seconds = time.perf_counter() - semantic_started
report = {
    'source_directory': str(source),
    'audit_scope': 'All 90,000 original PGNs checked for IDs, headers, date coverage, raw clock counts and agreement with metadata; a seeded random reservoir of 100 games per control (300 total) fully replayed with python-chess. Full 90,000-game move legality/clock coverage has NOT been verified. Original files not modified.',
    'full_header_audit': {
        'counts': dict(counts),
        'counts_by_time_control': dict(per_control),
        'dates': dict(sorted(dates.items())),
        'header_rejection_reasons': dict(header_rejects),
        'raw_clock_annotations_by_time_control': dict(clock_counts),
        'raw_clock_annotations_total': sum(clock_counts.values()),
        'metadata_unique_ids': len(metadata),
        'metadata_duplicate_ids': dict(metadata_duplicate_ids),
        'metadata_ids_missing_from_pgn': len(set(metadata) - ids),
        'metadata_mismatches': dict(mismatches),
        'elapsed_seconds': round(header_seconds, 3),
    },
    'semantic_sample': {
        'selection': 'Reservoir sampling independently per time control, random.Random(2026 + initial_time_s), 100 games per stratum; IDs listed below.',
        'counts': dict(sample_counts),
        'rejection_reasons': dict(sample_rejects),
        'clock_flags_among_valid_sample_games': dict(sample_flags),
        'valid_plies_by_time_control': dict(sample_plies),
        'valid_plies_total': sum(sample_plies.values()),
        'elapsed_seconds': round(semantic_seconds, 3),
        'games_per_second': round(sample_counts['checked_games']/semantic_seconds, 3),
        'game_ids_by_time_control': sample_ids,
    },
    'elapsed_seconds_total': round(time.perf_counter() - started, 3),
    'stockfish_benchmarked': False,
    'sampling_warning': 'All games come from 2026-10-01; suitable as an early-month pilot only, not a whole-month probability sample.',
}
(HERE / 'existing_data_audit.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k != 'semantic_sample'}, indent=2), flush=True)
print(json.dumps({k:v for k,v in report['semantic_sample'].items() if k != 'game_ids_by_time_control'}, indent=2), flush=True)
