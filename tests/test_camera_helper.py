import os
import sys
import struct
import time
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)

from camera_helper import CameraHelperTimeout, MAX_MESSAGE_SIZE, READY, read_message_before, write_message


class CameraHelperProtocolTest(unittest.TestCase):
    def test_message_round_trip(self):
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(write_fd, "wb", buffering=0) as writer:
                write_message(writer, READY, {"frame_width": 640, "frame_height": 480})

            status, payload = read_message_before(read_fd, time.time() + 1)
        finally:
            os.close(read_fd)

        self.assertEqual(status, READY)
        self.assertEqual(payload["frame_width"], 640)
        self.assertEqual(payload["frame_height"], 480)

    def test_read_message_times_out_when_helper_stalls(self):
        read_fd, write_fd = os.pipe()
        try:
            with self.assertRaises(CameraHelperTimeout):
                read_message_before(read_fd, time.time() + 0.01)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_read_message_rejects_oversized_payload(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, READY + struct.pack("!I", MAX_MESSAGE_SIZE + 1))

            with self.assertRaises(RuntimeError):
                read_message_before(read_fd, time.time() + 1)
        finally:
            os.close(read_fd)
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()
