Balanced Lichess sample: 30,000 games each of 1+0, 5+0, 10+0
================================================================

Files:
- 02_lichess_stratified_sample.py: collector (edit settings at top)
- 02_lichess_stratified_sample.ipynb: short Jupyter launcher

Instructions:
1. Put both files in the same local working folder.
2. Create an isolated environment and install dependencies:
   `python3 -m venv .venv`
   `.venv/bin/python -m pip install -r requirements.txt`
3. For the notebook, select the `Lichess sampling (Python 3)` kernel after installing:
   `.venv/bin/python -m ipykernel install --user --name lichess-sampling --display-name "Lichess sampling (Python 3)"`
4. In the Python script, set `QUOTA_PER_CONTROL=100` for a pilot.
5. Run the notebook or: `.venv/bin/python 02_lichess_stratified_sample.py`
6. Verify output counts and metadata in `data/lichess_2026-10_balanced/`.
7. Set `QUOTA_PER_CONTROL=30000` and rerun for the full sample.

The defaults use October 2026 Lichess Standard rated monthly games, with
PGN clocks. The code DOES NOT run Stockfish. It keeps only original PGN
and metadata for later conversion to move-level observations.

MODE="stream" uses HTTP streaming; the entire 31 GB archive is NOT saved,
and the reading stops when all quotas fill. This samples a month PREFIX,
not uniformly across the entire month. PICK_ONE_IN=3 provides a
reproducible hash subsample within that prefix.

MODE="local_reservoir" requires you to download the full .pgn.zst archive
first, then streams ALL games to obtain a more defensible whole-month
random sample. It does not create a 200+ GB uncompressed copy.

Important limitations:
- Collector checks headers and minimum %clk annotations; verify valid
  moves and clock completeness later with python-chess.
- Quotas create a deliberately balanced sample, not the natural mix of
  time controls on Lichess. Do not interpret pooled event rates as
  population rates without accounting for this.
- Some tournament games may include berserk mode, reducing initial time.
  Check anomalous early clock values and exclude/flag those games.
- Each player is rated separately by time control; do not interpret
  Bullet, Blitz and Rapid Elo as one perfectly comparable rating scale.
- Coursework requires instructor approval and no Kaggle dataset:
  verify the actual sampled dataset is not present on Kaggle.
- This collector has been syntax-checked and parser smoke-tested but
  has NOT been tested against the live Lichess archive from this runtime.

Source: https://database.lichess.org/standard/
