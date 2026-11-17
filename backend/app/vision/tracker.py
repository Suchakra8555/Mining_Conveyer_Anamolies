"""Continuous-loop belt segment tracking (modulo position arithmetic).

The belt is divided into N fixed segments with permanent IDs. A single fixed camera sees one point of the loop.
traveled_distance accumulates belt_speed*dt; the belt coordinate under the camera is (camera_pos - traveled) % L.
"""
from __future__ import annotations

import math


class BeltTracker:
    def __init__(self, length_m: float = 5000.0, segment_len_m: float = 50.0, camera_pos_m: float = 0.0):
        self.length = length_m
        self.seg_len = segment_len_m
        self.n = int(round(length_m / segment_len_m))
        self.camera = camera_pos_m
        self.traveled = 0.0
        self.passes: dict[int, int] = {}

    @staticmethod
    def segment_id(idx: int) -> str:
        return f"BS-{idx:03d}"

    def under_camera(self, traveled: float | None = None) -> int:
        d = self.traveled if traveled is None else traveled
        return int(((self.camera - d) % self.length) // self.seg_len) % self.n

    def position_of(self, idx: int) -> float:
        """Current position along the conveyor (metres) of the segment's start: belt_position = (origin + traveled) % L."""
        return (idx * self.seg_len + self.traveled) % self.length

    def advance(self, distance_m: float) -> list[int]:
        """Move the belt; return indices of every segment that crossed the camera (in order), even if several per tick."""
        if distance_m <= 0:
            return []
        start = self.traveled
        self.traveled += distance_m
        s0 = math.floor((self.camera - start) / self.seg_len)
        s1 = math.floor((self.camera - self.traveled) / self.seg_len)
        crossed = []
        for k in range(s0 - 1, s1 - 1, -1):          # successive segments pass the camera
            idx = k % self.n
            crossed.append(idx)
            self.passes[idx] = self.passes.get(idx, 0) + 1
        return crossed

    def state(self) -> dict:
        return {"traveled_m": round(self.traveled, 1), "loops": round(self.traveled / self.length, 3),
                "segment_under_camera": self.segment_id(self.under_camera()), "n_segments": self.n}
