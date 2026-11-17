# Implementation status

Last updated at the end of the build session. "Verified" means I ran it and looked at the result.

## Done and verified
| Item | Evidence |
|---|---|
| Simulator (10 stations, correlated channels, modes, scenarios, noise, benign oddities, severities, sensor faults, ground truth kept separate, reproducible) | `backend/tests/test_simulator.py` |
| Research Approach 2 (features, state classifier, median filter, duty-cycle detection, pattern matching) | `test_anomaly_model.py`; official repo read first |
| Failure-risk model (rolling windows, classifier + TTF regressor, temporal/seed split, held-out variants) | `test_failure_model.py`, `models/failure_prediction/metrics.json` |
| Data-quality validation and sensor health | `test_backend.py` |
| Health engine with stored evidence | API tests; screenshots |
| Backend (FastAPI), SQLite, Alembic `0001` + `0002` (`alembic upgrade head` run on a fresh DB) | `test_backend.py` |
| **PRD update 1**: ingestion decoupled from inference; lifespan background task; per-station watermark; idempotent processing | `test_ingestion_does_not_run_inference_and_processor_is_idempotent` |
| **PRD update 2**: anti-circular evaluation protocol and per-scenario/per-severity reporting | metrics JSON files; README |
| Dashboard (7 pages), custom SVG conveyor, polling | built with `npm run build`; screenshots of the running app in `docs/screenshots/` |
| Belt segment tracking + duplicate handling | `test_vision.py`, `test_backend.py` |
| Docs: README, 6 architecture docs with Mermaid, API doc, ADRs, research notes | this repo |

## Partial / with caveats
- **Vision model:** not a pretrained or trained model. A labelled heuristic detector on synthetic images; YOLO loading path written but never run (no weights, no torch). See README and `research/dataset_analysis.md`.
- **Value-level anomaly rules:** weak under the new protocol (recall LOW 0.04 / MEDIUM 0.32 / HIGH 0.51 averaged over kinds; 6 % false alarms). Not retuned on test by design. Needs a better method.
- **Time-to-failure:** MAE 4.52 h vs 4.77 h baseline on held-out seeds; not a useful estimate yet.
- **Component diagnosis:** idler/pulley/bearing are confused (idler F1 0.40).
- **Frontend:** built and screenshot-checked; no automated frontend tests.
- **Mermaid:** the 10 required diagrams exist across docs (architecture, sensor data flow, Approach 2, failure workflow, vision, ER, API sequence, sensor-health state, belt tracking, simulator states) but were not rendered through a Mermaid parser here, only written carefully.

## Known issues found while running the app
- **Degradation fools the state classifier (false "unexpected stop").** In the live demo ST-008 (simulated hydraulic degradation) lowers idle high-pressure from ~30 to ~20 bar. The state classifier was trained on healthy pressures, labels those idle minutes `A` (off) instead of `B` (idle), and Approach 2 then reports `UNEXPECTED_STOP` for cycles whose state sequence is a normal `CDC` (confirmed from the stored evidence and raw readings). The two models interact badly: a failing hydraulic system looks like a stopped drive. Not fixed (needs training the state classifier on degraded data or normalising idle pressure); the anomaly evaluation above does not cover this because test data contains no degradation during cycles.
- ST-002 shows a vibration anomaly plus an idler-wear prediction because the injected vibration anomaly resembles idler degradation (see README).

## Added after the first status report
| Item | State |
|---|---|
| Approach 3 (learned duty-cycle classifier), compared with Approach 2 | done, `approach3.py`, `approach3_metrics.json`, README |
| XGBoost and Gaussian Naive Bayes state-classifier comparison | done; XGBoost won validation and is the deployed state classifier (adds an `xgboost` dependency) |
| Evaluation plots (matplotlib) | done, `docs/figures/`, generated from the metrics JSON |
| uint8 input quantisation | done and evaluated; **no real size/latency saving shown** (inputs only; needs C export) |
| WebSockets | done as an optional "something changed" push; polling remains; tested |
| Docker / Compose | files written, `docker compose config` valid; **image never built** (no daemon) |
| Claude Code transcript | rendered to `ai_usage/transcript-claude-code.md` by `scripts/export_transcript.py` (e-mail redacted, tool output truncated, thinking omitted) |

## Still not done
A real vision dataset (blocked, below); C export / real MCU quantisation; GridSearchCV tuning as in the paper; Mermaid rendering check.

## Blocked
- Kaggle, Hugging Face, Roboflow, Zenodo and the PyTorch wheel index are not reachable from the build sandbox (proxy refusals; re-checked when the remaining items were done), so no real conveyor-defect dataset or pretrained weights, and no torch/ultralytics. A second GitHub search with licence filters found one CC0 repository that looks related (5 KB, so it cannot hold images; its data is hosted elsewhere). I did not attach or rely on it.
- Docker daemon is not running in the sandbox, so the image cannot be built here.

## Metrics near 1.0: investigation log (PRD update 2)

Rule applied: any metric near 1.0 is treated as a possible leak or an easy simulator until checked.

1. **First evaluation (before the update)** gave state macro-F1 0.987, abnormal precision 1.000, FPR 0.000, recall 0.97–0.99. Suspicious.
2. **Checks run** (in `anomaly_detection/train.py::diagnostics`, results in `metrics.json`):
   - *Feature leakage*: confirmed no truth column is in `FEATURE_COLUMNS`; tests assert ground truth columns are absent from feature frames, and failure-window features use only past data (`test_features_use_only_past_data`).
   - *Shuffled-label control*: classifier trained on shuffled state labels scores state macro-F1 **0.199** on test → the signal comes from real label–feature structure, not an artefact.
   - *Triviality baseline*: a speed-threshold rule (no learning) scores **0.955** on the same test data.
3. **Conclusion:** no leak found; the state task is too easy because simulator modes are cleanly separated in speed, and the structured anomalies produce very regular state sequences. Perfect precision came from having no benign look-alikes.
4. **Action taken:** added benign oddities, severities, higher test noise, seed split and held-out variants. Resulting test numbers are much lower where they should be (precision 0.66, FPR 0.083 driven by short pauses; value-rule recall 0.04–0.51).
5. **Still near 1.0 and still caveated:** state macro-F1 0.984 and structured-anomaly cycle recall 0.92–0.99 remain high. Reason is (3), not fixed by the changes: the simulator's mode separation is the easy part. A harder simulator (overlapping modes, drift, partial loads) is the next step.
6. **Failure model:** held-out-profile class recall 0.97 and fault-flagged recall 0.99 are high; flagged recall is high because degradation windows at moderate/high levels differ strongly from normal. The previous TTF MAE of 1.8 h (vs 3.1 h baseline) collapsed to 4.5 h (vs 4.8 h) once seeds/noise were separated: evidence that the old figure was circular.

## Honest deviations from the plan
- No `repositories/` layer (too little query code); queries live in routers/services.
- shadcn/ui not installed; hand-written Tailwind primitives.
- Python 3.13 instead of 3.12.
- Anomaly model file is named `state_classifier.joblib` (the validation winner can change between runs).

## Update: classifier comparison and Approach 3 (second evaluation pass)
- Adding XGBoost and Naive Bayes changed the validation winner from the decision tree to XGBoost (abnormal F1 0.990 vs 0.965). All anomaly test numbers in the README were refreshed from the regenerated `metrics.json`; the shuffled-label (0.199) and trivial-baseline (0.955) diagnostics are unchanged.
- Approach 3 gets precision 1.0 / FPR 0.0 on test. That is another "near 1.0" result; cause identified: it treats unseen sequence patterns as normal, so it is precise but misses the held-out intermittent family entirely (recall 0.0). Its validation scores tie across all six classifiers because validation has no unseen patterns.
- uint8 quantisation gave identical accuracy and no real saving; reported as such.
