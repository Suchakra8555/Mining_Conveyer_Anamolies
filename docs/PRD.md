# Requirements summary

The full PRD was supplied outside the repository. This file lists the requirements as implemented, with the PRD update applied, and points to where each lives. See `IMPLEMENTATION_STATUS.md` for what is done, partial or skipped.

| Area | Where |
|---|---|
| Simulator | `backend/app/simulator/engine.py` |
| Research anomaly detection (Approach 2) | `backend/app/ml/anomaly_detection/` |
| Failure-risk prediction | `backend/app/ml/failure_prediction/` |
| Vision + belt tracking | `backend/app/vision/`, `backend/app/services/vision_service.py` |
| Data quality | `backend/app/services/quality.py` |
| Health engine | `backend/app/services/health.py` |
| Backend/API/DB | `backend/app/api`, `database`, `services/pipeline.py`, `alembic/` |
| Dashboard | `frontend/src` |
| PRD update 1 | inference decoupled: background task + `last_processed_timestamp`, idempotent |
| PRD update 2 | anti-circular evaluation: noise, benign oddities, severities, seed/scenario splits, per-severity recall |
