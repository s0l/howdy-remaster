import configparser
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)

from recorders import video_capture


class FakeCapture:
    def __init__(self, opened=True, read_result=(True, None)):
        self.opened = opened
        self.read_result = read_result
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        return self.read_result

    def release(self):
        self.released = True


def config_with_device(path):
    config = configparser.ConfigParser()
    config["video"] = {"device_path": path, "warn_no_device": "false"}
    return config


class VideoCaptureHelpersTest(unittest.TestCase):
    def test_opencv_capture_source_converts_video_path_to_index(self):
        with mock.patch.object(video_capture.os.path, "realpath", return_value="/dev/video12"):
            self.assertEqual(video_capture.opencv_capture_source("/dev/v4l/by-path/cam"), 12)

    def test_opencv_capture_source_keeps_non_video_path(self):
        with mock.patch.object(video_capture.os.path, "realpath", return_value="/tmp/camera"):
            self.assertEqual(video_capture.opencv_capture_source("/tmp/camera"), "/tmp/camera")

    def test_score_device_prefers_ir_camera_names(self):
        with mock.patch.object(video_capture, "_video_device_name", return_value="ASUS IR camera"):
            score, name = video_capture._score_device("/dev/video2", probe=False)

        self.assertEqual(name, "ASUS IR camera")
        self.assertGreaterEqual(score, 120)

    def test_score_device_penalizes_metadata_nodes(self):
        with mock.patch.object(video_capture, "_video_device_name", return_value="Camera metadata"):
            score, _ = video_capture._score_device("/dev/video1", probe=False)

        self.assertLess(score, 0)

    def test_score_device_adds_gray_frame_bonus_when_probe_succeeds(self):
        gray = np.zeros((2, 2, 3), dtype=np.uint8)
        fake_capture = FakeCapture(opened=True, read_result=(True, gray))

        with mock.patch.object(video_capture, "_video_device_name", return_value="IR camera"):
            with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                score, _ = video_capture._score_device("/dev/video2", probe=True)

        self.assertGreaterEqual(score, 150)
        self.assertTrue(fake_capture.released)

    def test_discover_camera_devices_deduplicates_by_real_path_and_keeps_best_path(self):
        def fake_glob(pattern):
            if pattern == "/dev/v4l/by-path/*":
                return ["/dev/v4l/by-path/ir"]
            if pattern == "/dev/video*":
                return ["/dev/video2"]
            return []

        def fake_realpath(path):
            if path == "/dev/v4l/by-path/ir":
                return "/dev/video2"
            return path

        with mock.patch.object(video_capture.glob, "glob", side_effect=fake_glob):
            with mock.patch.object(video_capture.os.path, "exists", return_value=True):
                with mock.patch.object(video_capture.os.path, "realpath", side_effect=fake_realpath):
                    with mock.patch.object(video_capture, "_score_device", side_effect=[(130, "IR camera"), (120, "IR camera")]):
                        candidates = video_capture.discover_camera_devices(probe=False)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], "/dev/v4l/by-path/ir")
        self.assertEqual(candidates[0]["real_path"], "/dev/video2")

    def test_resolve_device_path_uses_existing_configured_path_without_scanning(self):
        config = config_with_device("/dev/video9")

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "discover_camera_devices") as discover:
                path = video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(path, "/dev/video9")
        discover.assert_not_called()

    def test_resolve_device_path_uses_cached_auto_device_before_scanning(self):
        config = config_with_device("auto")

        with mock.patch.object(video_capture, "_read_cached_device_path", return_value="/dev/video2"):
            with mock.patch.object(video_capture, "_camera_can_open", return_value=True):
                with mock.patch.object(video_capture, "discover_camera_devices") as discover:
                    path = video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(path, "/dev/video2")
        discover.assert_not_called()

    def test_resolve_device_path_scans_and_writes_cache_when_auto_cache_is_unusable(self):
        config = config_with_device("auto")
        candidates = [{"path": "/dev/video2", "real_path": "/dev/video2", "name": "IR camera", "score": 120}]

        with mock.patch.object(video_capture, "_read_cached_device_path", return_value="/dev/video0"):
            with mock.patch.object(video_capture, "_camera_can_open", return_value=False):
                with mock.patch.object(video_capture, "discover_camera_devices", return_value=candidates):
                    with mock.patch.object(video_capture, "_write_cached_device_path") as write_cache:
                        path = video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(path, "/dev/video2")
        write_cache.assert_called_once_with("/dev/video2")

    def test_cache_read_and_write_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "howdy", "device_path")
            with mock.patch.object(video_capture, "DEVICE_CACHE_PATH", cache_path):
                video_capture._write_cached_device_path("/dev/video2")

                self.assertEqual(video_capture._read_cached_device_path(), "/dev/video2")


if __name__ == "__main__":
    unittest.main()
