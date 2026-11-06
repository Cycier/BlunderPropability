"""Offline collection checks: small compressed fixtures, no archive download."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

SCRIPT = Path(__file__).with_name('02_lichess_stratified_sample.py')
spec = importlib.util.spec_from_file_location('sampling', SCRIPT)
sampling = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampling)
logging.getLogger('chess.pgn').setLevel(logging.CRITICAL)


def game(gid, control='60+0', date='2026.10.01', moves=None, result='1-0'):
    clock = {'60+0': '0:01:00', '300+0': '0:05:00', '600+0': '0:10:00'}[control]
    if moves is None:
        moves = f'1. e4 {{ [%clk {clock}] }} e5 {{ [%clk {clock}] }} 2. Nf3 {{ [%clk {clock}] }} Nc6 {{ [%clk {clock}] }} {result}'
    return (
        '[Event "Rated Blitz game"]\n'
        f'[Site "https://lichess.org/{gid}"]\n'
        f'[UTCDate "{date}"]\n[UTCTime "12:34:56"]\n'
        '[White "Alice"]\n[Black "Bob"]\n'
        '[WhiteElo "1500"]\n[BlackElo "1600"]\n'
        f'[TimeControl "{control}"]\n[Result "{result}"]\n'
        '[Termination "Normal"]\n\n' + moves + '\n\n'
    )


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_number = 0

    def tearDown(self):
        self.temp.cleanup()

    def fixture_args(self, records, quota=3, max_games=0, seed=2026):
        self.run_number += 1
        compressed = zstandard.ZstdCompressor().compress(''.join(records).encode())
        source = self.root / f'fixture{self.run_number}.pgn.zst'
        source.write_bytes(compressed)
        args = sampling.parse_args([
            '--local', str(source), '--expected-sha256', hashlib.sha256(compressed).hexdigest(),
            '--output', str(self.root / f'run{self.run_number}'),
            '--quota', str(quota), '--max-games', str(max_games), '--seed', str(seed),
        ])
        return args

    def rows(self, args):
        with (args.output / 'games_metadata.csv').open(newline='') as f:
            return list(csv.DictReader(f))

    def test_exact_bottom_k_reproducible_and_order_independent(self):
        records, ids = [], {}
        for i, control in enumerate(sampling.CONTROLS):
            ids[control] = [f'g{i}{j:06d}' for j in range(20)]
            records.extend(game(gid, control, f'2026.10.{j + 1:02d}') for j, gid in enumerate(ids[control]))
        expected = {
            control: set(sorted(game_ids, key=lambda gid: hashlib.sha256(f'2026|2026-10|{gid}'.encode()).hexdigest())[:3])
            for control, game_ids in ids.items()
        }
        selections = []
        for ordered in (records, records, list(reversed(records))):
            args = self.fixture_args(ordered)
            manifest = sampling.collect(args)
            self.assertTrue(manifest['complete'])
            self.assertTrue(manifest['whole_source_read'])
            self.assertTrue(manifest['source_integrity_verified'])
            rows = self.rows(args)
            selected = {tc: {r['game_id'] for r in rows if r['time_control'] == tc} for tc in ids}
            self.assertEqual(selected, expected)
            selections.append(selected)
            for name, expected_hash in manifest['output_sha256'].items():
                self.assertEqual(hashlib.sha256((args.output / name).read_bytes()).hexdigest(), expected_hash)
        self.assertEqual(selections[0], selections[1])
        self.assertEqual(selections[0], selections[2])

    def test_invalid_low_priority_games_do_not_fill_quota(self):
        valid_ids = ['v0000001', 'v0000002', 'v0000003', 'v0000004']
        invalid_ids = [f'i{j:07d}' for j in range(50)]
        invalid_ids.sort(key=lambda gid: hashlib.sha256(f'2026|2026-10|{gid}'.encode()).hexdigest())
        records = [game(gid).replace('{ [%clk 0:01:00] }', '{}', 1) for gid in invalid_ids[:5]]
        records += [game(gid) for gid in valid_ids]
        args = self.fixture_args(records, quota=2)
        manifest = sampling.collect(args)
        expected = set(sorted(valid_ids, key=lambda gid: hashlib.sha256(f'2026|2026-10|{gid}'.encode()).hexdigest())[:2])
        self.assertEqual({r['game_id'] for r in self.rows(args)}, expected)
        self.assertGreater(manifest['statistics']['validation_reject/missing_or_duplicate_clock'], 0)
        self.assertEqual(manifest['counts']['60+0'], 2)

    def test_duplicate_ids_never_create_extra_records(self):
        record = game('d0000001')
        args = self.fixture_args([record, record, game('d0000002'), record], quota=3)
        manifest = sampling.collect(args)
        self.assertEqual(manifest['counts']['60+0'], 2)
        self.assertEqual(len(self.rows(args)), 2)
        self.assertEqual(manifest['statistics']['duplicate_selected_id'], 2)
        self.assertFalse(manifest['quotas_met'])

    def test_short_resignation_and_clock_flags(self):
        raw = game('s0000001', moves='1. e4 { [%clk 0:00:30] } e5 { [%clk 0:01:00] } 1-0')
        meta, reason = sampling.validate_game(raw, sampling.read_tags(raw), '2026-10')
        self.assertIsNone(reason)
        self.assertEqual(meta['plies'], 2)
        self.assertTrue(meta['suspected_berserk'])
        self.assertTrue(meta['first_clock_below_nominal'])
        self.assertEqual(meta['white_first_clock_s'], 30)
        raw = game('s0000002', moves='1. e4 { [%clk 0:00:58] } e5 { [%clk 0:01:00] } 2. Nf3 { [%clk 0:00:59] } 1-0')
        meta, reason = sampling.validate_game(raw, sampling.read_tags(raw), '2026-10')
        self.assertIsNone(reason)
        self.assertEqual(meta['clock_increases'], 1)

    def test_validation_rejects_bad_inputs(self):
        normal = game('b0000001')
        cases = {
            'unrated': normal.replace('Rated Blitz', 'Unrated Blitz'),
            'missing_clock': normal.replace('{ [%clk 0:01:00] }', '{}', 1),
            'duplicate_clock': normal.replace('[%clk 0:01:00]', '[%clk 0:01:00] [%clk 0:01:00]', 1),
            'bad_clock': normal.replace('[%clk 0:01:00]', '[%clk broken]', 1),
            'illegal_san': normal.replace('1. e4', '1. e5'),
            'terminal_result': game('b0000002', moves='1. f3 { [%clk 0:01:00] } e5 { [%clk 0:01:00] } 2. g4 { [%clk 0:01:00] } Qh4# { [%clk 0:01:00] } 1-0'),
            'unrecognized_token': normal.replace('1. e4', '1. e4 nonsense'),
            'result_disagreement': normal.rstrip().removesuffix('1-0') + '0-1\n',
            'unfinished': normal.replace('[Result "1-0"]', '[Result "*"]'),
            'wrong_month': normal.replace('2026.10.01', '2026.09.01'),
            'bad_elo': normal.replace('[WhiteElo "1500"]', '[WhiteElo "?"]'),
            'custom_start': normal.replace('[Result', '[SetUp "1"]\n[Result'),
            'bot': normal.replace('[Result', '[WhiteTitle "BOT"]\n[Result'),
            'bad_id': normal.replace('b0000001', 'not_an_id'),
        }
        for label, raw in cases.items():
            with self.subTest(label=label):
                meta, reason = sampling.validate_game(raw, sampling.read_tags(raw), '2026-10')
                self.assertIsNone(meta)
                self.assertIsNotNone(reason)

    def test_export_replay_detects_metadata_tampering(self):
        args = self.fixture_args([game('e0000001')], quota=1)
        sampling.collect(args)
        report = sampling.validate_outputs(args.output)
        self.assertTrue(report['valid'])
        self.assertEqual(report['unique_valid_games'], 1)
        csv_path = args.output / 'games_metadata.csv'
        rows = self.rows(args)
        rows[0]['white_elo'] = '999'
        with csv_path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=sampling.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        # Update the file hash: the replay must still find semantic inconsistency.
        manifest_path = args.output / 'dataset_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['output_sha256']['games_metadata.csv'] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'validation failed'):
            sampling.validate_outputs(args.output)
        report = json.loads((args.output / 'validation_report.json').read_text())
        self.assertFalse(report['valid'])
        self.assertTrue(any('white_elo' in issue for issue in report['issues_first_100']))

    def test_no_overwrite(self):
        args = self.fixture_args([game('o0000001')], quota=1)
        sampling.collect(args)
        before = (args.output / 'dataset_manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):
            sampling.collect(args)
        self.assertEqual((args.output / 'dataset_manifest.json').read_bytes(), before)

    def test_capped_pilot_never_claims_complete(self):
        records = [game('p0000001', '60+0'), game('p0000002', '300+0'), game('p0000003', '600+0'), game('p0000004')]
        args = self.fixture_args(records, quota=1, max_games=3)
        manifest = sampling.collect(args)
        self.assertTrue(manifest['quotas_met'])
        self.assertFalse(manifest['whole_source_read'])
        self.assertFalse(manifest['complete'])
        self.assertEqual(manifest['status'], 'pilot_or_incomplete')

    def test_truncated_archive_fails_integrity_and_writes_failure_manifest(self):
        args = self.fixture_args([game('t0000001')], quota=1)
        data = args.local.read_bytes()
        args.local.write_bytes(data[:-3])
        with self.assertRaises((ValueError, zstandard.ZstdError)):
            sampling.collect(args)
        manifest = json.loads((args.output / 'dataset_manifest.json').read_text())
        self.assertEqual(manifest['status'], 'failed')
        self.assertFalse(manifest['complete'])
        self.assertFalse((args.output / 'games_metadata.csv').exists())

    def test_remote_read_failure_writes_failure_manifest(self):
        args = self.fixture_args([game('r0000001')], quota=1)
        args.local = None

        class BrokenRaw(io.BytesIO):
            def read(self, size=-1):
                raise OSError('simulated interrupted network read')

        class Response:
            raw = BrokenRaw()
            headers = {'Content-Length': '1234'}
            def raise_for_status(self):
                pass
            def close(self):
                self.raw.close()

        class Session:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def get(self, *args, **kwargs):
                return Response()

        with patch.object(sampling, 'http_session', return_value=Session()):
            with self.assertRaisesRegex(OSError, 'interrupted network'):
                sampling.collect(args)
        manifest = json.loads((args.output / 'dataset_manifest.json').read_text())
        self.assertEqual(manifest['status'], 'failed')
        self.assertFalse(manifest['complete'])
        self.assertIn('simulated interrupted network read', manifest['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
