import configparser
import os
import stat
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
        self.grabbed = False
        self.settings = []
        self.values = {}

    def isOpened(self):
        return self.opened

    def read(self):
        return self.read_result

    def grab(self):
        self.grabbed = True

    def release(self):
        self.released = True

    def set(self, prop, value):
        self.settings.append((prop, value))
        self.values[prop] = value
        return True

    def get(self, prop):
        return self.values.get(prop, 0)


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
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "discover_camera_devices") as discover:
                    path = video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(path, "/dev/video9")
        discover.assert_not_called()

    def test_resolve_device_path_rejects_unsafe_configured_path_by_default(self):
        config = config_with_device("/tmp/not-a-camera")

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=False):
                with self.assertRaises(SystemExit) as err:
                    video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(err.exception.code, 14)

    def test_resolve_device_path_allows_unsafe_configured_path_when_enabled(self):
        config = config_with_device("/tmp/custom-camera")
        config["video"]["allow_unsafe_device_path"] = "true"

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path") as safe_check:
                path = video_capture.resolve_device_path(config, warn=False)

        self.assertEqual(path, "/tmp/custom-camera")
        safe_check.assert_not_called()

    def test_safe_video_device_path_requires_character_video_device(self):
        fake_stat = os.stat_result((stat.S_IFCHR | 0o600, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        with mock.patch.object(video_capture.os, "stat", return_value=fake_stat):
            with mock.patch.object(video_capture.os.path, "realpath", return_value="/dev/video2"):
                self.assertTrue(video_capture._is_safe_video_device_path("/dev/v4l/by-path/ir"))

    def test_safe_video_device_path_rejects_non_video_character_device(self):
        fake_stat = os.stat_result((stat.S_IFCHR | 0o600, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        with mock.patch.object(video_capture.os, "stat", return_value=fake_stat):
            with mock.patch.object(video_capture.os.path, "realpath", return_value="/dev/input/event0"):
                self.assertFalse(video_capture._is_safe_video_device_path("/dev/input/event0"))

    def test_safe_video_device_path_rejects_regular_files(self):
        fake_stat = os.stat_result((stat.S_IFREG | 0o600, 0, 0, 0, 0, 0, 0, 0, 0, 0))

        with mock.patch.object(video_capture.os, "stat", return_value=fake_stat):
            with mock.patch.object(video_capture.os.path, "realpath", return_value="/dev/video2"):
                self.assertFalse(video_capture._is_safe_video_device_path("/tmp/video2"))

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
                self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(cache_path)).st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(os.stat(cache_path).st_mode), 0o600)

    def test_video_capture_can_skip_constructor_warmup_read(self):
        config = config_with_device("/dev/video9")
        fake_capture = FakeCapture(opened=True)

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config, warmup=False)

        self.assertFalse(fake_capture.grabbed)
        capture.release()

    def test_video_capture_warms_camera_by_default(self):
        config = config_with_device("/dev/video9")
        fake_capture = FakeCapture(opened=True)

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config)

        self.assertTrue(fake_capture.grabbed)
        capture.release()

    def test_video_capture_reapplies_manual_exposure_after_each_read(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        config = config_with_device("/dev/video9")
        config["video"]["exposure"] = "42"
        fake_capture = FakeCapture(opened=True, read_result=(True, frame))

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config, warmup=False)

        capture.read_frame()

        self.assertEqual(
            fake_capture.settings,
            [
                (video_capture.cv2.CAP_PROP_AUTO_EXPOSURE, 1.0),
                (video_capture.cv2.CAP_PROP_EXPOSURE, 42.0),
            ],
        )
        capture.release()

    def test_video_capture_tunes_for_backlit_dark_face(self):
        config = config_with_device("/dev/video9")
        fake_capture = FakeCapture(opened=True)
        fake_capture.values = {
            video_capture.cv2.CAP_PROP_BRIGHTNESS: 10,
            video_capture.cv2.CAP_PROP_GAIN: 20,
            video_capture.cv2.CAP_PROP_EXPOSURE: 30,
        }

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config, warmup=False)

        result = capture.tune_for_dark_face(backlit=True)

        self.assertTrue(result["changed"])
        self.assertIn((video_capture.cv2.CAP_PROP_BACKLIGHT, 1.0), fake_capture.settings)
        self.assertIn((video_capture.cv2.CAP_PROP_BRIGHTNESS, 11.0), fake_capture.settings)
        self.assertIn((video_capture.cv2.CAP_PROP_GAIN, 21.0), fake_capture.settings)
        self.assertIn((video_capture.cv2.CAP_PROP_AUTO_EXPOSURE, 1.0), fake_capture.settings)
        self.assertIn((video_capture.cv2.CAP_PROP_EXPOSURE, 31.0), fake_capture.settings)
        capture.release()

    def test_video_capture_tuning_stops_after_configured_steps(self):
        config = config_with_device("/dev/video9")
        config["video"]["auto_exposure_max_steps"] = "1"
        fake_capture = FakeCapture(opened=True)

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config, warmup=False)

        first = capture.tune_for_dark_face(backlit=False)
        second = capture.tune_for_dark_face(backlit=False)

        self.assertTrue(first["changed"])
        self.assertEqual(second["reason"], "max_steps")
        capture.release()

    def test_video_capture_exposure_bracket_tries_positive_offsets_first(self):
        config = config_with_device("/dev/video9")
        config["video"]["exposure_bracket_range"] = "1.0"
        config["video"]["exposure_bracket_step"] = "0.5"
        fake_capture = FakeCapture(opened=True)
        fake_capture.values = {video_capture.cv2.CAP_PROP_EXPOSURE: 10}

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    capture = video_capture.VideoCapture(config, warmup=False)

        first = capture.advance_exposure_bracket()
        second = capture.advance_exposure_bracket()
        third = capture.advance_exposure_bracket()
        fourth = capture.advance_exposure_bracket()
        exhausted = capture.advance_exposure_bracket()

        self.assertEqual(first["offset"], 0.5)
        self.assertEqual(first["target"], 10.5)
        self.assertEqual(second["offset"], 1.0)
        self.assertEqual(third["offset"], -0.5)
        self.assertEqual(fourth["offset"], -1.0)
        self.assertEqual(exhausted["reason"], "exhausted")
        capture.release()

    def test_parse_v4l2_controls_reads_exposure_range(self):
        text = """
                     auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
                         1: Manual Mode
                         3: Aperture Priority Mode
             exposure_time_absolute 0x009a0902 (int)    : min=50 max=10000 step=1 default=166 value=166 flags=inactive, has-min-max
        """

        controls = video_capture.parse_v4l2_controls(text)
        name, control = video_capture.exposure_control_from_v4l2(controls)

        self.assertEqual(name, "exposure_time_absolute")
        self.assertEqual(control["minimum"], 50)
        self.assertEqual(control["maximum"], 10000)
        self.assertEqual(control["step"], 1)

    def test_video_capture_native_exposure_bracket_uses_multipliers(self):
        config = config_with_device("/dev/video9")
        fake_capture = FakeCapture(opened=True)
        fake_capture.values = {video_capture.cv2.CAP_PROP_EXPOSURE: 166}
        controls = {
            "exposure_time_absolute": {
                "minimum": 50,
                "maximum": 10000,
                "step": 1,
                "default": 166,
                "value": 166,
            }
        }

        with mock.patch.object(video_capture.os.path, "exists", return_value=True):
            with mock.patch.object(video_capture, "_is_safe_video_device_path", return_value=True):
                with mock.patch.object(video_capture, "_open_opencv_capture", return_value=fake_capture):
                    with mock.patch.object(video_capture, "read_v4l2_controls", return_value=controls):
                        capture = video_capture.VideoCapture(config, warmup=False)

        first = capture.advance_exposure_bracket()
        second = capture.advance_exposure_bracket()
        third = capture.advance_exposure_bracket()

        self.assertEqual(first["strategy"], "native_exposure_absolute")
        self.assertEqual(first["target"], 249)
        self.assertEqual(second["target"], 332)
        self.assertEqual(third["target"], 498)
        capture.release()


if __name__ == "__main__":
    unittest.main()
