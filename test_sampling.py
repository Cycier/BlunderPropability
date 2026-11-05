"""Small offline tests. Run: python test_sampling.py"""
import csv
import importlib.util
import json
import logging
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard

path = Path(__file__).with_name("02_lichess_stratified_sample.py")
spec = importlib.util.spec_from_file_location("collector", path)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
logging.getLogger("chess.pgn").setLevel(logging.CRITICAL)


def make_game(game_id, control):
    seconds = int(control.split("+")[0])
    clock = f"0:{seconds // 60:02d}:00"
    return (
        '[Event "Rated Blitz game"]\n'
        f'[Site "https://lichess.org/{game_id}"]\n'
        '[UTCDate "2026.10.15"]\n[UTCTime "12:00:00"]\n'
        '[WhiteElo "1500"]\n[BlackElo "1600"]\n'
        f'[TimeControl "{control}"]\n[Result "1-0"]\n\n'
        f'1. e4 {{ [%clk {clock}] }} e5 {{ [%clk {clock}] }} 1-0\n\n'
    )


class CollectionTests(unittest.TestCase):
    def test_fixed_seed_matches_textbook_reservoir(self):
        records = [make_game(f"g{i:07d}", "60+0") for i in range(30)]
        rng = random.Random(2026)
        expected = records[:5]
        for n in range(6, len(records) + 1):
            position = rng.randint(0, n - 1)
            if position < 5:
                expected[position] = records[n - 1]
        with patch.multiple(collector, POOL_SIZE=5, MAX_GAMES=None):
            actual, seen, scanned, ended = collector.sample_games("".join(records).splitlines(True))
            repeated, _, _, _ = collector.sample_games("".join(records).splitlines(True))
        self.assertEqual(actual["60+0"], expected)
        self.assertEqual(actual, repeated)
        self.assertEqual(seen["60+0"], 30)
        self.assertEqual(scanned, 30)
        self.assertTrue(ended)

    def test_validation_rejects_missing_clock_and_illegal_move(self):
        good = make_game("v0000001", "60+0")
        self.assertEqual(collector.check_game(good), 2)  # Legal short resignation.
        self.assertIsNone(collector.check_game(good.replace("[%clk 0:01:00]", "", 1)))
        self.assertIsNone(collector.check_game(good.replace("1. e4", "1. e5")))
        self.assertIsNone(collector.check_game(good.replace("[%clk 0:01:00]", "[%clk 0:01:00] [%clk 0:01:00]", 1)))

    def test_compressed_collection_all_controls_and_no_overwrite(self):
        records = []
        for group, control in enumerate(collector.TIME_CONTROLS):
            records += [make_game(f"g{group}{i:06d}", control) for i in range(10)]
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "small.pgn.zst"
            archive.write_bytes(zstandard.ZstdCompressor().compress("".join(records).encode()))
            output = Path(folder) / "result"
            settings = dict(LOCAL_ARCHIVE=archive, OUTPUT_DIR=output, GAMES_PER_CONTROL=3,
                            POOL_SIZE=5, MAX_GAMES=None)
            with patch.multiple(collector, **settings):
                summary = collector.run()
                with self.assertRaises(FileExistsError):
                    collector.run()
            self.assertEqual(summary["saved"], {control: 3 for control in collector.TIME_CONTROLS})
            self.assertEqual(summary["games_scanned"], 30)
            with (output / "games_metadata.csv").open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 9)
            self.assertEqual(len({row["game_id"] for row in rows}), 9)
            self.assertEqual(json.loads((output / "collection_summary.json").read_text()), summary)
            for label in collector.TIME_CONTROLS.values():
                with (output / f"games_{label}.pgn").open() as handle:
                    self.assertEqual(len(list(collector.read_games(handle))), 3)

    def test_pilot_cap_is_marked_as_partial(self):
        records = [make_game(f"p{i:07d}", "60+0") for i in range(5)]
        with patch.multiple(collector, POOL_SIZE=2, MAX_GAMES=3):
            _, _, scanned, ended = collector.sample_games("".join(records).splitlines(True))
        self.assertEqual(scanned, 3)
        self.assertFalse(ended)


if __name__ == "__main__":
    unittest.main(verbosity=2)
