# State transitions

## Simulator operating modes

```mermaid
stateDiagram-v2
    [*] --> OFF
    OFF --> IDLE
    IDLE --> OPERATIONAL
    OPERATIONAL --> ACTIVE
    ACTIVE --> OPERATIONAL
    OPERATIONAL --> IDLE
    IDLE --> OFF
    ACTIVE --> OFF: abnormal (unexpected stop)
    IDLE --> ACTIVE: abnormal (abnormal start-up)
    OPERATIONAL --> OFF: abnormal
```

Normal duty cycle: IDLE → OPERATIONAL → ACTIVE → OPERATIONAL → IDLE, which Approach 2 sees as B C D C B. `is_valid_transition` and `ABNORMAL_TRANSITIONS` in `simulator/engine.py` encode these edges; a test checks that normal cycles use only valid ones.

## Sensor reliability

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN
    UNKNOWN --> ONLINE: valid readings arrive
    ONLINE --> DEGRADED: more than 10 % of last 30 readings flagged
    DEGRADED --> ONLINE: flags clear
    DEGRADED --> OFFLINE: more than 80 % flagged
    ONLINE --> OFFLINE: no data for 10 intervals / 5 straight disconnects
    OFFLINE --> DEGRADED: partial data returns
    OFFLINE --> ONLINE: clean data returns
```

## Station health (output of the health engine)

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN
    UNKNOWN --> NORMAL: enough valid data, no issue
    NORMAL --> ABNORMAL: active anomaly
    ABNORMAL --> PREDICTED_FAILURE: risk >= 0.5
    NORMAL --> PREDICTED_FAILURE: risk >= 0.5
    PREDICTED_FAILURE --> ABNORMAL: prediction expires / risk drops
    ABNORMAL --> NORMAL: anomalies resolved
    NORMAL --> OFFLINE: sensor offline
    ABNORMAL --> OFFLINE: sensor offline
    PREDICTED_FAILURE --> OFFLINE: sensor offline
    OFFLINE --> NORMAL: sensor back, no issue
```

Status is recomputed from scratch each tick by priority rules (OFFLINE > PREDICTED_FAILURE > ABNORMAL > UNKNOWN > NORMAL), so the arrows above describe what is possible, not a stored state machine.
