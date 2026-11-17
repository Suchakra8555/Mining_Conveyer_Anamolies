# Architecture decisions

**ADR-1 Modular monolith.** One FastAPI process holds simulator, models, vision, DB. Load is ~5 readings/s; queues, brokers or services would add failure modes and no capacity. Boundaries are enforced by module structure instead.

**ADR-2 SQLite + SQLAlchemy + Alembic.** Zero infrastructure for a local assessment; ORM keeps PostgreSQL possible. Cost: single writer, no retention policy. WAL mode is on.

**ADR-3 Polling, not WebSockets.** 2.5 s polling is enough for 2-second ticks and degrades gracefully (TanStack Query keeps stale data when a poll fails).

**ADR-4 Two separate models.** The paper's method detects abnormal *duty cycles*; it does not predict component failure. The failure model is my extension, trained on simulated degradation, and the UI labels its basis `SIMULATED_DEGRADATION`.

**ADR-5 Inference is decoupled from ingestion (PRD update).** Ingestion validates and stores. A lifespan background task processes readings newer than a per-station `last_processed_timestamp`, idempotently. Reason: request latency must not depend on model runtime, and a crashed inference run must be retryable without duplicating results. Replaced the first version, which ran inference every N ticks inside the tick.

**ADR-6 Health is rules over evidence, not a model.** Offline sensors must never read as healthy; anomalies, predictions and sensor reliability fail in different ways. The evidence list is stored so the UI can explain every colour.

**ADR-7 Sensor faults are not equipment faults.** Quality problems are stored, blanked before ML, and surfaced as sensor health. Deviates from the paper, which marks cycles with missing data abnormal.

**ADR-8 Vision: interface + honest fallback.** No real defect dataset or weights could be fetched (network policy). The detector interface supports YOLO weights; the active detector is a labelled heuristic, evaluated only on synthetic images. Tracking, deduplication and location metadata are independent of the detector.

**ADR-9 Loop handling by permanent segments.** 100 fixed segment IDs with modulo position arithmetic. Matching uses class + overlap *or containment* because growth breaks IoU. See README for what remains unsolved (odometry drift, one visible belt face, multi-pass confirmation).

**ADR-10 Anti-circular evaluation (PRD update).** The simulator defines the anomalies, so a model can relearn the generator. Mitigations: per-channel noise, benign oddities labelled normal, severity-graded subtle anomalies, train/validation/test split by seed, chronological order and held-out scenario variants, selection on validation only, and per-scenario/per-severity recall. Metrics near 1.0 are treated as a finding to investigate (see IMPLEMENTATION_STATUS.md).
