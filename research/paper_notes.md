# Paper notes

*On-device Anomaly Detection in Conveyor Belt Operations* (Martinez-Rau, Zhang, Oelmann, Bader), arXiv:2411.10729. Official code: github.com/lucianomrau/on_device_anomaly_detection_in_conveyor_belt_operations (cloned and read for this project; not vendored here).

What the repo contains: `approach1.ipynb`, `approach2.ipynb`, `approach3.ipynb`, `custom_functions.py`, `my_functions.py`, results, and an example input file. The real training CSVs are not public (confidential), so published numbers cannot be reproduced from this repo.

What the problem is in the paper: detect abnormal *duty cycles* of a conveyor drive from three drive signals (speed, high pressure, low pressure) at 1-minute resolution, on a microcontroller. It is not component-level failure prediction.

Things read directly from the code (Approach 2, `approach2.ipynb` and `custom_functions.py`):
- features: `extract_features` (raw, centred rolling means of 3 and 5, differential pressure);
- state labels A/B/C/D, `balance_dataset` (SMOTE + under-sampling), classifiers rf/dt/xtree/mlp, `medfilt` with kernel 3;
- duty-cycle detection: `Speed_order3 > 2.5`;
- `apply_heuristic_rules`: non-repeated label sequence per cycle, normal sequences `["CDC","CD"]`, `extra_lenght = 3` minutes margin, idle (`B`) required before/after, any missing minute makes the cycle abnormal.
- State meanings (A off, B idle, C/D operating phases) are inferred from how the code uses them, not stated in the code. My mapping C = transition, D = steady operation is an interpretation.
