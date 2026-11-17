# ML pipelines

## Anomaly detection: research Approach 2

```mermaid
flowchart TD
    A["1-minute station readings: speed, high pressure, low pressure"]
    B["Preprocess: resample, interpolate gaps up to 5 min, clip speed at 0"]
    C["Features: raw + rolling mean order 3 and 5 + differential pressure (12)"]
    D["State classifier A/B/C/D (scaler + ExtraTrees)"]
    E["Duty-cycle detector: Speed_order3 > 2.5"]
    F["3-sample median filter on state labels"]
    G["State-sequence extraction inside each cycle, strip edge A/B"]
    H["Pattern matching: CDC or CD, idle B before and after, no data gap"]
    I["NORMAL / ABNORMAL / INDETERMINATE + category + severity"]
    A --> B --> C
    C --> D --> F --> G
    B --> E --> G
    G --> H --> I
```

States are the paper's A (off), B (idle), C (transition), D (steady operation), mapped from the simulator's OFF, IDLE, OPERATIONAL, ACTIVE. Only the state classifier is learned; cycle detection and pattern matching are rules, as in the paper. Categories: `UNEXPECTED_STOP` (machine goes to A, not B, after the cycle), `ABNORMAL_STARTUP` (sequence begins with D), `INTERMITTENT_OPERATION` (two or more D runs), `OTHER_SEQUENCE`. Deviations from the official code are listed in the README and `research/methodology.md`.

A second, separate check (`signal_checks.py`) applies calibrated thresholds to the last 30 minutes for value-level anomalies. It is an extension and its source is stored as `SIGNAL_RULE` so the dashboard can tell the two apart.

## Failure-risk prediction

```mermaid
flowchart TD
    A["Station readings, quality problems blanked"]
    B["Resample to 1 min, keep running rows only (rpm > 10)"]
    C["Window features: 60 min stats and slopes, 12 h drift, running hours 24 h, rule flags"]
    D{"At least 15 running samples?"}
    E["No prediction"]
    F["Classifier: NORMAL + 7 degradation classes"]
    G["risk = 1 - P(NORMAL)"]
    H{"risk >= 0.5?"}
    I["Regressor: hours to failure"]
    J["Persist FailurePrediction (component, failure type, risk, severity, TTF, basis)"]
    A --> B --> C --> D
    D -- no --> E
    D -- yes --> F --> G --> H
    H -- yes --> I --> J
    H -- no --> J
```

Training labels come from simulator ground truth: a window is labelled with a scenario if its degradation level at the window end is ≥ 0.25 and NORMAL if the level is 0 (ambiguous in-between windows are dropped). Hard negatives (overloads, slippage, injected vibration, sensor faults) are included as NORMAL. Features use only data up to the window end (tested). The severity bands are fixed: ≥ 0.8 CRITICAL, ≥ 0.65 HIGH, ≥ 0.5 MEDIUM, otherwise LOW.
