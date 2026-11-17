# Vision pipeline and belt tracking

```mermaid
flowchart TD
    A["Camera capture for a belt segment (sample image or upload)"]
    B["Load + resize to max 640 px"]
    C["Detector: YOLO weights if present, otherwise heuristic demo"]
    D["Keep supported classes only: CRACK, TEAR, HOLE, ABRASION, EDGE_DAMAGE"]
    E["Associate with belt segment ID + simulated position"]
    F{"Same segment, same class, boxes overlap or contain?"}
    G["New incident: lower segment health"]
    H["Repeat observation: count++, update latest size, keep max score"]
    I["Persist, save annotated image"]
    A --> B --> C --> D --> E --> F
    F -- no --> G --> I
    F -- yes --> H --> I
```

## Belt segment tracking

```mermaid
flowchart LR
    A["Belt speed at ST-001 x tick length"] --> B["traveled += distance"]
    B --> C["Segments crossed since last tick: floor((camera - traveled)/segment length)"]
    C --> D["For each crossed segment: pass_count++, last_observed, position = (origin + traveled) mod length"]
    D --> E{"Segment has a camera image?"}
    E -- yes --> F["Run detector (image stage grows with pass count)"]
    E -- no --> G["Record the pass only"]
```

The conveyor is 5,000 m with 100 segments of 50 m (`BS-000` to `BS-099`). The simulation marks 8 segments as damaged; each has three images of the same defect at growing size (wear stage = passes // 2, capped at 2). Segment position, camera position and the damage assignment are simulated. The `location_source` column says so on every record.

Matching rule (`vision.detector.same_defect`): IoU ≥ 0.3 **or** the smaller box is ≥ 70 % inside the larger one. The second condition exists because a growing defect has a low IoU against its earlier self.
