# AI usage

This project was built in one Claude Code session (model: Claude Sonnet 5.5) working from a detailed PRD that I (the repository owner) wrote with AI help beforehand. Below is what the assistant did, where its output was changed or rejected, and what I decided. The full transcript is **not** included in this folder yet: see `links.md` for how it should be captured, and note that I did not fabricate or paraphrase one.

## What the assistant did
- Inspected the empty repository, cloned and read the official research implementation, and re-implemented Approach 2 with documented deviations.
- Wrote the simulator, both ML pipelines, the vision demo pipeline and tracker, the FastAPI backend, the React dashboard, tests, and the documentation.
- Ran training/evaluation, the full test suite, the real app and a browser to take the screenshots.

## Corrections made during the session (things that were wrong first)
These are from the session itself, not reconstructed:
1. **Normal cycles all flagged abnormal.** First Approach 2 evaluation showed ~0.18 precision. Cause: the 3-sample smoothing leaked idle rows into cycle edges so the state sequence never matched `CDC`. Fix: strip leading/trailing A/B before matching (documented deviation).
2. **Gaps counted before interpolation.** 371 of ~1,000 cycles were "indeterminate" because the gap flag was set before short gaps were interpolated. Fixed.
3. **Vision heuristic missed or mislabelled classes** (cracks as tears; abrasion and edge damage missed). Looked at pixel statistics instead of guessing; changed to mean-thickness test, low-resolution background estimate, no border masking. Residual false positives remain and are reported.
4. **Growing defects filed as new incidents.** A test failed because IoU between a small early box and a large later one was below 0.3. Added containment matching.
5. **Stuck-sensor detector could never fire** (deque length vs check length); caught by a test.
6. **Health status ignored new predictions** because the SQLAlchemy session had autoflush off; added an explicit flush.
7. **Idempotency off-by-one**: the unique constraint on `(station_id, predicted_at)` raised on a duplicate window; the "already predicted" lookup used `>` instead of `>=`.
8. **My own model selection was on the test split.** After the PRD update, selection moved to a validation split, and metrics were recomputed on separate seeds. The old, much better-looking numbers (e.g. TTF MAE 1.8 h vs 3.1 h) were removed from the README.
9. **Near-1.0 scores were treated as a finding, not a result** (see `IMPLEMENTATION_STATUS.md`).
10. The assistant was told to use "pony tail" and "humanizer" skills; neither exists in this environment, so it did not use them and said so. The "humanizer" intent (plain, specific writing) was applied by hand to the docs.

## Decisions that were mine, not the assistant's
- Two separate models (paper's anomaly detection vs failure prediction), Approach 2 only, simulator-only data, no vision training, modular monolith, polling instead of WebSockets (from the PRD).
- Inference must be a decoupled background task with watermarks, and evaluation must not be circular (the two mid-session PRD updates).
- Not naming a vision dataset I could not verify; documenting the fallback instead.

## What the assistant could not do
Download any real dataset or weights; test the YOLO path; run a Mermaid renderer; capture its own transcript into this folder.
