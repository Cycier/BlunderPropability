# Team handoff — 18 November 2026

Dataset construction is complete: **9,000 games, 586,827 raw positions**. Use the three uncleaned CSVs in [`data/MAIN`](../data/MAIN/). All teammates should start from these same raw files; the historical pilot folders are not additional training data.

## What to share

1. `data/MAIN/`, including `provenance/`: raw data, exact 9,000-game membership and engine/run records.
2. `Python Scripts/CleanData.py` and `Python Scripts/Complexity.py`: reference cleaning implementation plus its schema/clock dependencies.
3. `docs/DATASET_9000.md`, `docs/FEATURE_DICTIONARY.md` and this handoff.
4. Original PGNs/source metadata in `data/results/` if the team needs to reconstruct positions or audit source clocks.

The raw files have 86 columns: `y`, 60 candidate predictors, a one-space visual spacer, and 24 metadata columns. **Do not make X by merely dropping y.** Use the explicit `predictor_columns` list in `data/MAIN/provenance/engine_protocol.json`, or `Complexity.PREDICTOR_COLUMNS`. Actual moves, played evaluations, evaluation losses and label statuses reveal outcomes and are excluded from predictors.

The target is a loss strictly greater than 200cp from the mover's perspective, plus the documented mate rules. Exactly 200cp is y=0. There are 80 unclassified rows, all inconsistent mate evaluations. Do not turn those blanks into zero. See [the dataset record](DATASET_9000.md).

## Cleaning reference

The team can clean the raw data independently. `CleanData.py` is a reference, not a requirement to reuse identical choices. It removes diagnostic/invalid/duplicate/unclassified rows and the spacer, masks anomalous clocks using information available by that turn, retains mate-labeled rows with missing `pre_eval_cp`, adds `pre_eval_cp_missing`, and leaves remaining numerical missingness blank.

The processing-PC context reports reference-cleaner counts of **194,191 / 202,549 / 190,007** kept rows, totaling **586,747** and retaining all 9,000 games. Those counts match the valid labels checked here. Final cleaned CSVs/report were **not** part of this delivery, and the cleaner was not rerun during consolidation.

If reproducing the reference cleaning later, use a fresh output folder. From the project root, with a working Python environment and python-chess installed:

```python
from pathlib import Path
import sys

project = Path.cwd()
sys.path.insert(0, str(project / "Python Scripts"))
import CleanData

CleanData.run(
    input_dir=project / "data/MAIN",
    output_dir=project / "data/cleaned_reference_9000",
)
```

Pass the two arguments explicitly: changing module constants after importing the cleaner does not change the function's already-bound defaults. Keep raw files unchanged, and save each teammate's cleaning choices/output separately.

## Checks before modeling

- Confirm raw row totals: **194,221 / 202,576 / 190,030** and 3,000 distinct games per control.
- Record exclusions, missingness, class counts and changes to the reference cleaning policy.
- PGN clocks are after-move clocks. The exported clock features use earlier own annotations; current thinking time is not a predictor. Do not fill earlier clocks from future rows.
- Freeze whole-game training/test memberships, balancing time controls. Keep all positions from one game together in holdout and cross-validation.
- Fit learned imputation, scaling and encoding inside training folds. Compare the same rows across feature groups.
- Compare a constant training-frequency baseline with L2 logistic models: ratings/clocks/move number; add elementary move/board features; then add pre-move engine evaluation and its missing indicator.
- Choose regularization/classification thresholds on validation only. Evaluate the locked procedure once on test. Report average precision, log loss, Brier score/reliability and appropriate classification metrics.

No models have been fitted in this consolidation. Repeated players can cross game splits, so claims concern unseen games, not necessarily unseen players. The source collection covers early 1 October, not a month-wide random sample. Interpretation is predictive, not causal.

## Reproducibility status

The final CSVs, exact game list, original source PGNs, producing engine binary, run manifest and protocol are consolidated. The subsequently supplied home-PC exporter and checkpoint runner are archived in [`data/MAIN/provenance/home_pc_source/`](../data/MAIN/provenance/home_pc_source/). After restoring one missing final newline, the exporter matches the recorded run hash exactly. Its existing feature/clock/label/move-processing functions match the original script; the runner reproduces the exact 9,000-game selection. The main student scripts remain unchanged. External sleep-inhibition/supervisor launch configuration was not supplied. For code reproduction, see the archive README and recorded cap/settings. The raw data validation passed; it is not proof that finite-budget engine labels are ground truth.

Dataset eligibility under the no-Kaggle rule is still unconfirmed in available records. The old exposé/lecturer response and 825-game plan are historical documents, indexed in [docs/README.md](README.md).
