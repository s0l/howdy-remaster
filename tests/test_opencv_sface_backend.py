import configparser
import os
import sys
import types
import unittest

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)

paths_factory = types.ModuleType("paths_factory")
paths_factory.face_detection_yunet_path = lambda: "/tmp/face_detection.onnx"
paths_factory.face_recognition_sface_path = lambda: "/tmp/face_recognition.onnx"
paths_factory.face_data_dir_path = lambda: "/tmp"
sys.modules.setdefault("paths_factory", paths_factory)

from face_backends.opencv_sface import OpenCVSFaceBackend


class OpenCVSFaceBackendTest(unittest.TestCase):
    def backend(self):
        config = configparser.ConfigParser()
        config["opencv_sface"] = {
            "match_threshold": "0.5",
            "detector_score_threshold": "0.9",
            "detector_nms_threshold": "0.3",
            "detector_top_k": "5000",
        }
        return OpenCVSFaceBackend(config)

    def test_match_selects_highest_cosine_similarity(self):
        backend = self.backend()
        known = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.5, 0.5, 0.0],
        ]

        index, score = backend.match(known, [0.0, 2.0, 0.0])

        self.assertEqual(index, 1)
        self.assertAlmostEqual(score, 1.0)

    def test_match_handles_empty_known_encodings(self):
        backend = self.backend()

        index, score = backend.match([], [1.0, 0.0, 0.0])

        self.assertIsNone(index)
        self.assertIsNone(score)

    def test_match_handles_zero_vectors_without_nan(self):
        backend = self.backend()

        index, score = backend.match([[0.0, 0.0, 0.0]], [1.0, 0.0, 0.0])

        self.assertEqual(index, 0)
        self.assertFalse(np.isnan(score))
        self.assertEqual(score, 0.0)

    def test_is_match_uses_configured_threshold(self):
        backend = self.backend()

        self.assertFalse(backend.is_match(None))
        self.assertFalse(backend.is_match(0.499))
        self.assertTrue(backend.is_match(0.5))
        self.assertTrue(backend.is_match(0.9))

    def test_face_rect_converts_values_to_ints(self):
        backend = self.backend()

        self.assertEqual(backend.face_rect([1.7, 2.1, 30.9, 40.2]), (1, 2, 30, 40))


if __name__ == "__main__":
    unittest.main()
