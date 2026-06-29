import os
import sys
import unittest

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)

from frame_quality import (
    DEFAULT_UNLIT_P95_THRESHOLD,
    classify_face_lighting,
    face_region,
    is_backlit_scene,
    is_face_too_dark,
    is_unlit_frame,
    light_metrics,
)


class FrameQualityTest(unittest.TestCase):
    def test_dark_background_with_lit_face_is_not_unlit(self):
        frame = np.zeros((10, 10), dtype=np.uint8)
        frame[:, :2] = 180

        self.assertFalse(is_unlit_frame(frame, DEFAULT_UNLIT_P95_THRESHOLD))
        self.assertGreater(light_metrics(frame)["dark_percent"], 60)

    def test_fully_dim_frame_is_unlit(self):
        frame = np.full((10, 10), 12, dtype=np.uint8)

        self.assertTrue(is_unlit_frame(frame, DEFAULT_UNLIT_P95_THRESHOLD))

    def test_face_darkness_uses_face_region_not_whole_frame(self):
        frame = np.zeros((20, 20), dtype=np.uint8)
        frame[5:15, 5:15] = 180

        self.assertFalse(is_face_too_dark(frame, [5, 5, 10, 10], 60))
        self.assertGreater(light_metrics(frame)["dark_percent"], 60)

    def test_bright_background_with_dark_face_is_backlit(self):
        frame = np.full((20, 20), 220, dtype=np.uint8)
        frame[5:15, 5:15] = 20

        lighting = classify_face_lighting(frame, [5, 5, 10, 10], 50)

        self.assertEqual(lighting["state"], "backlit")
        self.assertTrue(lighting["backlit"])

    def test_global_backlit_scene_detects_window_like_frame(self):
        frame = np.zeros((20, 20), dtype=np.uint8)
        frame[:, :4] = 230

        self.assertTrue(is_backlit_scene(frame))

    def test_global_backlit_scene_rejects_uniform_bright_frame(self):
        frame = np.full((20, 20), 230, dtype=np.uint8)

        self.assertFalse(is_backlit_scene(frame))

    def test_face_region_is_clipped_to_frame_bounds(self):
        frame = np.ones((10, 10), dtype=np.uint8)
        roi = face_region(frame, [-2, -2, 5, 5])

        self.assertEqual(roi.shape, (3, 3))


if __name__ == "__main__":
    unittest.main()
