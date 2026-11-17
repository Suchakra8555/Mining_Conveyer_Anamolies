# Methodology and deviations

Implemented: Approach 2 (see README and `docs/architecture/ml-pipeline.md`). Not implemented: Approach 1, Approach 3.

Deviations from the official code, each deliberate:

| Paper / code | This project | Why |
|---|---|---|
| Confidential real drive data | Simulator data | the real data is not available |
| Speed threshold 2.5 on real units | 2.5 rpm, calibrated to simulator idle noise | no equipment-specific value to reuse |
| SMOTE + under-sampling, GridSearchCV | `class_weight='balanced'`, fixed parameters from the paper's grid | fewer dependencies, simpler |
| Missing data → abnormal | Missing data → `INDETERMINATE` | a dropped sensor is not a conveyor fault |
| Sequence as observed | Leading/trailing A/B stripped | 3-sample smoothing leaks idle rows into cycle edges |
| Binary normal/abnormal | + category and severity rules | dashboard needs an explanation |
| Whole-file offline processing | streaming; cycles cut by the window are skipped | avoided false start-up alarms |

Extensions that are not from the paper: rule-based value checks (`signal_checks.py`), the failure-risk model, data-quality validation, health engine, vision.

Evaluation protocol (PRD update): see `docs/decisions/architecture-decisions.md` ADR-10 and the docstrings of the two `train.py` files. Metric files: `models/anomaly_detection/metrics.json`, `models/failure_prediction/metrics.json`, `models/vision/demo_eval.json`.
