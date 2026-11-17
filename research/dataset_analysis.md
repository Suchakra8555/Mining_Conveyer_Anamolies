# Vision dataset investigation

Goal: a public conveyor-belt defect dataset with a clear licence, and pretrained weights trained on it.

What I tried from the build environment:
- Hugging Face model/dataset search API (`huggingface.co`): connection refused by the egress proxy (403 on CONNECT).
- Roboflow Universe, Kaggle, Zenodo: unreachable (proxy refused).
- PyTorch CPU wheel index (`download.pytorch.org`): unreachable, so torch/ultralytics were not installed.
- GitHub repository search ("conveyor belt defect yolo", "...tear detection weights", "...damage detection pretrained"): a handful of repositories, none with a licence field set; several were listings that say the data must be obtained through sponsorship. I did not download or rely on any of them and I am not recording dataset sizes or class lists for them because I did not verify any.

Result: **no real dataset and no pretrained conveyor-defect weights were used.** Nothing in this repo claims otherwise.

Fallback implemented: synthetic images (`backend/app/vision/synth.py`) with known boxes for five classes (crack, tear, hole, abrasion, edge damage) and a labelled heuristic detector. The synthetic set has 30 images: 6 clean, and 8 damaged segments × 3 growth stages. Limitations: not photographic, no dirt/lighting/texture variation, tuned and evaluated on the same images.

To replace the fallback: choose a licensed dataset (record source, licence, size, classes, annotation format here), put weights at `models/vision/conveyor_defect.pt`, install CPU torch + `ultralytics`, evaluate on a held-out split, and only then set `validated`.
