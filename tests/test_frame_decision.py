import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)

from frame_decision import FrameDecisionWindow, clamp_decision_window


class FrameDecisionWindowTest(unittest.TestCase):
    def test_clamps_window_size(self):
        self.assertEqual(clamp_decision_window(0), 1)
        self.assertEqual(clamp_decision_window(3), 3)
        self.assertEqual(clamp_decision_window(99), 10)
        self.assertEqual(clamp_decision_window("bad"), 3)

    def test_alternating_dark_no_face_does_not_tune(self):
        window = FrameDecisionWindow(3)
        window.add(face_count=1, dark_percent=35, p95=130)
        window.add(face_count=0, dark_percent=91, p95=106)
        window.add(face_count=1, dark_percent=36, p95=129)

        self.assertTrue(window.ready())
        self.assertTrue(window.alternating_bad_frames())
        self.assertFalse(window.stable_no_face_backlit())
        self.assertFalse(window.stable_face_dark())

    def test_stable_face_dark_triggers_after_window(self):
        window = FrameDecisionWindow(3)
        for _index in range(3):
            window.add(face_count=1, face_dark=True, dark_percent=80, p95=45)

        self.assertTrue(window.stable_face_dark())

    def test_stable_backlit_no_face_triggers_after_window(self):
        window = FrameDecisionWindow(3)
        for _index in range(3):
            window.add(face_count=0, backlit=True, dark_percent=70, p95=220)

        self.assertTrue(window.stable_no_face_backlit())

    def test_single_frame_window_keeps_reactive_behavior(self):
        window = FrameDecisionWindow(1)
        window.add(face_count=0, backlit=True, dark_percent=70, p95=220)

        self.assertTrue(window.ready())
        self.assertTrue(window.stable_no_face_backlit())

    def test_stable_bad_stream_requires_persistent_unlit_or_black_frames(self):
        window = FrameDecisionWindow(3)
        window.add(face_count=0, black=True, unlit=True)
        window.add(face_count=0, unlit=True)
        window.add(face_count=0, unlit=True)

        self.assertTrue(window.stable_bad_stream())


if __name__ == "__main__":
    unittest.main()
