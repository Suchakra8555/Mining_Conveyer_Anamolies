# Data flow

One live tick (default: every 2 s of wall time, advancing 60 s of simulated time):

```mermaid
sequenceDiagram
    participant L as Background loop
    participant S as Simulator
    participant Q as Quality validator
    participant D as SQLite
    participant M as ML services
    participant H as Health engine
    participant F as Dashboard

    L->>S: step()
    S-->>L: one reading per station
    L->>Q: validate each reading
    Q-->>L: status OK / MISSING / STUCK / SPIKE / ...
    L->>D: store readings with quality status
    L->>L: advance belt tracker, capture images for crossed segments
    L->>D: store vision detections (new incident or repeat)
    alt every 5th tick
        L->>D: load last 6 h / 36 h per station, quality-problem values blanked
        L->>M: Approach 2 cycles, rule checks, failure risk
        M->>D: cycles, anomalies, predictions
    end
    L->>H: evaluate every station
    H->>D: status + evidence
    F->>D: poll summary, stations, anomalies, predictions (via API)
```

Sensor data path in words: the simulator emits values with random missing entries and optional injected sensor faults. The validator labels each reading but never drops it; the label is stored. Before ML, readings labelled SPIKE, OUT_OF_RANGE, BAD_TIMESTAMP (whole row) or STUCK (the stuck channel) are set to missing, so a faulty sensor cannot look like a faulty conveyor. Missing values then go through short-gap interpolation (≤ 5 min) for Approach 2 features.

Warm start (`Pipeline.setup`) runs the same validator on 12 h of vectorised history, replays belt travel and camera captures over it, back-fills hourly failure predictions so risk trends exist, then switches to live stepping.
