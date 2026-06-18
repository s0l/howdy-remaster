"""Killable camera helper used by PAM compare.

The parent process owns authentication and face matching. This helper owns the
camera driver calls that may block inside OpenCV/V4L native code.
"""

import configparser
import ctypes
import io
import json
import os
import select
import signal
import struct
import subprocess
import sys
import time


CAP_PROP_FRAME_WIDTH = 3
CAP_PROP_FRAME_HEIGHT = 4
READY = b"R"
FRAME = b"F"
ERROR = b"E"
READ_FRAME = b"F"
SET_PROPERTY = b"S"
QUIT = b"Q"
HEADER_SIZE = 5
MAX_MESSAGE_SIZE = 64 * 1024 * 1024
PR_SET_PDEATHSIG = 1


class CameraHelperTimeout(TimeoutError):
    pass


def set_parent_death_signal():
    """Ask Linux to terminate the helper if compare.py disappears."""
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))

    # Close the race where the parent died just before prctl was installed.
    if os.getppid() == 1:
        os.kill(os.getpid(), signal.SIGTERM)


def _encode_payload(status, payload):
    if status == ERROR:
        return str(payload).encode("utf-8", errors="replace")
    if status == FRAME:
        import numpy as np

        buffer = io.BytesIO()
        frame, gsframe = payload
        np.savez(buffer, frame=frame, gsframe=gsframe)
        return buffer.getvalue()

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _decode_payload(status, payload):
    if status == ERROR:
        return payload.decode("utf-8", errors="replace")
    if status == FRAME:
        import numpy as np

        with np.load(io.BytesIO(payload), allow_pickle=False) as data:
            return data["frame"], data["gsframe"]

    return json.loads(payload.decode("utf-8"))


def write_message(stream, status, payload):
    data = _encode_payload(status, payload)
    stream.write(status + struct.pack("!I", len(data)) + data)
    stream.flush()


def _read_exact_before(fd, size, deadline):
    chunks = []
    remaining_size = size

    while remaining_size > 0:
        remaining_time = max(0.0, deadline - time.time())
        if remaining_time <= 0:
            raise CameraHelperTimeout()

        ready, _writable, _errors = select.select([fd], [], [], remaining_time)
        if not ready:
            raise CameraHelperTimeout()

        chunk = os.read(fd, remaining_size)
        if not chunk:
            raise EOFError("camera helper exited")

        chunks.append(chunk)
        remaining_size -= len(chunk)

    return b"".join(chunks)


def read_message_before(fd, deadline):
    header = _read_exact_before(fd, HEADER_SIZE, deadline)
    status = header[:1]
    payload_size = struct.unpack("!I", header[1:])[0]
    if payload_size > MAX_MESSAGE_SIZE:
        raise RuntimeError("camera helper message is too large")
    payload = _read_exact_before(fd, payload_size, deadline)

    return status, _decode_payload(status, payload)


class CameraHelperClient:
    def __init__(self, timeout, logger=None):
        self.timeout = timeout
        self.logger = logger
        self.process = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--helper"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + timeout
        status, payload = self._read_message(deadline)
        if status == ERROR:
            self.close(kill=True)
            raise RuntimeError(payload)
        if status != READY:
            self.close(kill=True)
            raise RuntimeError("camera helper sent an invalid startup message")

        self.metadata = payload
        self.fw = payload.get("frame_width") or 1
        self.fh = payload.get("frame_height") or 1

    def _read_message(self, deadline):
        if self.process.stdout is None:
            raise RuntimeError("camera helper stdout is unavailable")

        try:
            return read_message_before(self.process.stdout.fileno(), deadline)
        except CameraHelperTimeout:
            self.close(kill=True)
            raise
        except EOFError:
            raise RuntimeError("camera helper exited before sending a frame")
        except RuntimeError:
            self.close(kill=True)
            raise

    def get(self, prop):
        if prop == CAP_PROP_FRAME_WIDTH:
            return self.fw
        if prop == CAP_PROP_FRAME_HEIGHT:
            return self.fh
        return 0

    def read_frame_before(self, deadline):
        if self.process.stdin is None:
            raise RuntimeError("camera helper stdin is unavailable")

        try:
            self.process.stdin.write(READ_FRAME)
            self.process.stdin.flush()
        except BrokenPipeError as err:
            raise RuntimeError("camera helper is not accepting frame requests") from err

        status, payload = self._read_message(deadline)
        if status == ERROR:
            raise RuntimeError(payload)
        if status != FRAME:
            raise RuntimeError("camera helper sent an invalid frame message")

        return payload

    def set(self, prop, setting, timeout=1.0):
        if self.process.stdin is None:
            raise RuntimeError("camera helper stdin is unavailable")

        payload = json.dumps([prop, setting], separators=(",", ":")).encode("utf-8")
        try:
            self.process.stdin.write(SET_PROPERTY + struct.pack("!I", len(payload)) + payload)
            self.process.stdin.flush()
        except BrokenPipeError as err:
            raise RuntimeError("camera helper is not accepting property changes") from err

        status, response = self._read_message(time.time() + timeout)
        if status == ERROR:
            raise RuntimeError(response)
        if status != READY:
            raise RuntimeError("camera helper sent an invalid property response")

        return bool(response)

    def release(self):
        self.close()

    def close(self, kill=False):
        if getattr(self, "process", None) is None:
            return

        process = self.process
        if process.poll() is not None:
            return

        if not kill and process.stdin is not None:
            try:
                process.stdin.write(QUIT)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

        try:
            process.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            process.terminate()
            process.wait(timeout=0.5)
            return
        except subprocess.TimeoutExpired:
            pass

        process.kill()
        process.wait()


def helper_main():
    set_parent_death_signal()

    # Reserve stdout for the binary frame protocol. Legacy capture code may
    # print warnings/errors; send those to stderr so the protocol stays intact.
    protocol_stdout = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    sys.stdout = sys.stderr

    import paths_factory

    config = configparser.ConfigParser()
    config.read(paths_factory.config_file_path())

    try:
        import cv2
        from recorders.video_capture import VideoCapture

        video_capture = VideoCapture(config, warmup=False)
        metadata = {
            "frame_width": video_capture.internal.get(cv2.CAP_PROP_FRAME_WIDTH) or 1,
            "frame_height": video_capture.internal.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1,
        }
        write_message(protocol_stdout, READY, metadata)
    except SystemExit as err:
        write_message(protocol_stdout, ERROR, "camera helper exited with code {}".format(err.code))
        return int(err.code) if isinstance(err.code, int) else 1
    except BaseException as err:
        write_message(protocol_stdout, ERROR, err)
        return 1

    while True:
        command = sys.stdin.buffer.read(1)
        if not command or command == QUIT:
            return 0

        if command == READ_FRAME:
            try:
                frame, gsframe = video_capture.read_frame()
                write_message(protocol_stdout, FRAME, (frame, gsframe))
            except SystemExit as err:
                write_message(protocol_stdout, ERROR, "camera helper exited with code {}".format(err.code))
                return int(err.code) if isinstance(err.code, int) else 1
            except BaseException as err:
                write_message(protocol_stdout, ERROR, err)
            continue

        if command == SET_PROPERTY:
            try:
                size_data = sys.stdin.buffer.read(4)
                if len(size_data) != 4:
                    return 1
                payload_size = struct.unpack("!I", size_data)[0]
                if payload_size > MAX_MESSAGE_SIZE:
                    write_message(protocol_stdout, ERROR, "property message is too large")
                    continue
                payload = sys.stdin.buffer.read(payload_size)
                if len(payload) != payload_size:
                    return 1
                prop, setting = json.loads(payload.decode("utf-8"))
                result = video_capture.internal.set(prop, setting)
                write_message(protocol_stdout, READY, result)
            except BaseException as err:
                write_message(protocol_stdout, ERROR, err)
            continue

        write_message(protocol_stdout, ERROR, "invalid camera helper command")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--helper":
        sys.exit(helper_main())

    print("camera_helper.py is an internal Howdy helper")
    sys.exit(2)
