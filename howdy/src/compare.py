# Compare incoming video with known faces
# Running in a local python instance to get around PATH issues

import atexit
import configparser
import json
import logging
import os
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

import cv2

import paths_factory
import snapshot
from camera_helper import CameraHelperClient, CameraHelperTimeout
from face_backends import load_face_backend
from frame_quality import (
    classify_face_lighting,
    is_backlit_scene,
    is_black_frame,
    is_unlit_frame,
    light_metrics,
)
from i18n import _


def setup_logger():
    log_dir = "/var/log/howdy"
    try:
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        os.chmod(log_dir, 0o700)
        log_file = os.path.join(log_dir, "compare.log")
        fd = os.open(log_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(log_file, 0o600)
        logging.basicConfig(
            filename=log_file,
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
    except PermissionError:
        logging.basicConfig(level=logging.CRITICAL)

    return logging.getLogger("howdy.compare")


logger = setup_logger()
timings = {"st": time.time()}
DEFAULT_TIMEOUT = 10
video_capture_released = False


def exit(code: int | None = None) -> None:
    """Exit while closing howdy-gtk properly"""
    global gtk_proc

    if "gtk_proc" in globals() and gtk_proc is not None:
        try:
            os.killpg(gtk_proc.pid, signal.SIGTERM)
        except Exception as err:
            logger.warning("Failed to terminate gtk_proc process group: %s", err)
            try:
                gtk_proc.terminate()
            except Exception as terminate_err:
                logger.warning("Failed to terminate gtk_proc: %s", terminate_err)

    if code is not None:
        sys.exit(code)


def release_video_capture() -> None:
    """Release the camera as soon as auth no longer needs more frames."""
    global video_capture_released

    if video_capture_released or "video_capture" not in globals():
        return

    video_capture_released = True
    try:
        video_capture.release()
        logger.info("Released video capture device")
    except Exception as err:
        logger.warning("Failed to release video capture device: %s", err)


def handle_termination(signum, _frame) -> None:
    logger.info("Received signal %d, terminating helper processes", signum)
    release_video_capture()
    exit(128 + signum)


signal.signal(signal.SIGTERM, handle_termination)
signal.signal(signal.SIGINT, handle_termination)


def make_snapshot(type: str) -> None:
    """Generate snapshot after detection"""
    snapshot.generate(
        snapframes,
        [
            type + _(" LOGIN"),
            _("Date: ") + datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M:%S UTC"),
            _("Scan time: ") + str(round(time.time() - timings["fr"], 2)) + "s",
            _("Frames: ")
            + str(frames)
            + " ("
            + str(round(frames / max(time.time() - timings["fr"], 0.001), 2))
            + "FPS)",
            _("Hostname: ") + os.uname().nodename,
            _("Best score: ") + str(round(best_score, 3)),
        ],
    )


def send_to_ui(type: str, message: str) -> None:
    """Send message to the auth ui"""
    global gtk_proc

    if "gtk_proc" not in globals():
        return

    message = type + "=" + message + " \n"

    try:
        if gtk_proc.poll() is None:
            gtk_proc.stdin.write(bytearray(message.encode("utf-8")))
            gtk_proc.stdin.flush()
    except IOError:
        pass


def read_frame_before(deadline: float):
    try:
        return video_capture.read_frame_before(deadline)
    except CameraHelperTimeout:
        logger.error("Timed out waiting for camera frame")
        release_video_capture()
        exit(11)
    except RuntimeError as err:
        logger.error("Camera helper failed while reading a frame: %s", err)
        release_video_capture()
        exit(14)


def compatible_encodings(raw_models, backend):
    labels = []
    encodings = []

    for model in raw_models:
        if model.get("backend") != backend.name:
            continue

        for encoding in model.get("data", []):
            encodings.append(encoding)
            labels.append(model)

    return labels, encodings


def format_scan_status(scanned_frames: int, skipped_black: int, skipped_dark: int) -> str:
    frame_label = "frame" if scanned_frames == 1 else "frames"
    skipped = []
    if skipped_black:
        skipped.append("%d black" % skipped_black)
    if skipped_dark:
        skipped.append("%d dark" % skipped_dark)

    message = "Scanned %d %s" % (scanned_frames, frame_label)
    if skipped:
        message += " (skipped %s)" % ", ".join(skipped)
    return message


def print_end_report(match, match_index, labels, frame):
    def print_timing(label, key):
        print("  %s: %dms" % (label, round(timings[key] * 1000)))

    print(_("Time spent"))
    print_timing(_("Starting up"), "in")
    print(_("  Open cam + load libs: %dms") % (round(max(timings["ll"], timings["ic"]) * 1000,)))
    print_timing(_("  Opening the camera"), "ic")
    print_timing(_("  Importing recognition libs"), "ll")
    print_timing(_("Searching for known face"), "fl")
    print_timing(_("Total time"), "tt")

    print(_("\nResolution"))
    width = video_capture.fw or 1
    print(_("  Native: %dx%d") % (height, width))
    scale_height, scale_width = frame.shape[:2]
    print(_("  Used: %dx%d") % (scale_height, scale_width))

    print(_("\nFrames searched: %d (%.2f fps)") % (frames, frames / max(timings["fl"], 0.001)))
    print(_("Black frames ignored: %d ") % (black_tries,))
    print(_("Dark frames ignored: %d ") % (dark_tries,))
    print(_("Winning score: %.3f") % (match,))
    print(_('Winning model: %d ("%s")') % (match_index, labels[match_index]["label"]))


if len(sys.argv) < 2:
    exit(12)

user = sys.argv[1]
models = []
encodings = []
labels = []
black_tries = 0
dark_tries = 0
frames = 0
snapframes = []
best_score = 0.0
gtk_proc = None

config = configparser.ConfigParser()
config.read(paths_factory.config_file_path())

timings["ll"] = time.time()
try:
    face_backend = load_face_backend(config)
except (FileNotFoundError, ValueError) as err:
    print(err)
    logger.error("Could not initialize face backend: %s", err)
    exit(1)
timings["ll"] = time.time() - timings["ll"]

try:
    with open(paths_factory.user_model_path(user)) as f:
        models = json.load(f)
except (FileNotFoundError, ValueError):
    exit(10)

if len(models) < 1:
    exit(10)

labels, encodings = compatible_encodings(models, face_backend)
if not encodings:
    print(
        _("No face models for backend {backend}, please run howdy add again").format(
            backend=face_backend.name
        )
    )
    logger.error("No compatible face models for backend %s", face_backend.name)
    exit(10)

end_report = config.getboolean("debug", "end_report", fallback=False)
save_failed = config.getboolean("snapshots", "save_failed", fallback=False)
save_successful = config.getboolean("snapshots", "save_successful", fallback=False)
gtk_stdout = config.getboolean("debug", "gtk_stdout", fallback=False)
rotate = config.getint("video", "rotate", fallback=0)
timeout = config.getint("video", "timeout", fallback=DEFAULT_TIMEOUT)
confirmation_required = os.environ.get("HOWDY_CONFIRM_AUTH") == "1"

gtk_pipe = sys.stdout if gtk_stdout else subprocess.DEVNULL
gtk_stdout_pipe = subprocess.PIPE if confirmation_required else gtk_pipe

try:
    gtk_proc = subprocess.Popen(
        [paths_factory.gtk_bin_path(), "--start-auth-ui"],
        stdin=subprocess.PIPE,
        stdout=gtk_stdout_pipe,
        stderr=gtk_pipe,
        start_new_session=True,
    )
    atexit.register(exit)
except FileNotFoundError:
    pass

send_to_ui("M", _("Starting up..."))


def request_ui_confirmation() -> bool:
    if not confirmation_required:
        return True

    if gtk_proc is None or gtk_proc.stdout is None or gtk_proc.poll() is not None:
        logger.error("Confirmation requested but auth UI is unavailable")
        return False

    send_to_ui("C", "1")
    send_to_ui("M", _("Face recognized"))
    send_to_ui("S", _("Approve this authentication request?"))

    deadline = time.time() + 30
    while time.time() < deadline:
        ready, _writable, _errors = select.select([gtk_proc.stdout], [], [], 0.2)
        if not ready:
            if gtk_proc.poll() is not None:
                logger.info("Auth UI exited before confirmation")
                return False
            continue

        response = gtk_proc.stdout.readline()
        if not response:
            return False

        response_text = response.decode("utf-8", errors="replace").strip()
        if response_text == "ALLOW":
            logger.info("Authentication approved by auth UI")
            return True
        if response_text == "DENY":
            logger.info("Authentication denied by auth UI")
            return False

    logger.info("Timed out waiting for auth UI confirmation")
    return False

timings["in"] = time.time() - timings["st"]
logger.info("Face backend %s initialized", face_backend.name)

timings["ic"] = time.time()
logger.info("Opening video capture device")
try:
    video_capture = CameraHelperClient(timeout=timeout, logger=logger)
except CameraHelperTimeout:
    logger.error("Timed out opening camera helper")
    exit(11)
except RuntimeError as err:
    logger.error("Could not open camera helper: %s", err)
    exit(14)
logger.info("Video capture opened successfully")
timings["ic"] = time.time() - timings["ic"]
logger.info("Camera opened in %.2fs", timings["ic"])

max_height = config.getfloat("video", "max_height", fallback=320.0)
height = video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1
if rotate == 2:
    height = video_capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 1
scaling_factor = (max_height / height) or 1

unlit_threshold = config.getfloat("video", "unlit_threshold", fallback=24.0)
dark_threshold = config.getfloat("video", "dark_threshold", fallback=60.0)
end_report = config.getboolean("debug", "end_report", fallback=False)

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

send_to_ui("M", _("Identifying you..."))

valid_frames = 0
timings["fr"] = time.time()
deadline = timings["fr"] + timeout
dark_running_total = 0

while True:
    frames += 1

    elapsed = time.time() - timings["fr"]
    if time.time() > deadline:
        if save_failed:
            make_snapshot(_("FAILED"))

        logger.error(
            "Timeout reached after %.2fs, scanned %d frames (%d valid, %d dark)",
            elapsed,
            frames,
            valid_frames,
            dark_tries,
        )

        if valid_frames == 0 and dark_tries > 0:
            print(_("All frames were unlit, please check IR emitter, device_fps or unlit_threshold in config"))
            print(
                _("Average darkness: {avg}, P95 threshold: {threshold}").format(
                    avg=str(dark_running_total / max(1, dark_tries)),
                    threshold=str(unlit_threshold),
                )
            )
            exit(13)

        exit(11)

    frame, gsframe = read_frame_before(deadline)
    raw_gsframe = gsframe
    metrics = light_metrics(raw_gsframe)

    if save_failed or save_successful:
        if len(snapframes) < 3:
            snapframes.append(frame)

    logger.debug(
        "Frame %d: dark_pixels=%.1f%%, p95=%.1f, valid_frames=%d, dark_tries=%d",
        frames,
        metrics["dark_percent"],
        metrics["p95"],
        valid_frames,
        dark_tries,
    )

    if is_black_frame(raw_gsframe):
        black_tries += 1
        send_to_ui("S", format_scan_status(frames, black_tries, dark_tries))
        continue

    valid_frames += 1
    send_to_ui("S", format_scan_status(frames, black_tries, dark_tries))
    raw_scan_frame = raw_gsframe
    gsframe = clahe.apply(raw_gsframe)

    if scaling_factor != 1:
        frame = cv2.resize(
            frame,
            None,
            fx=scaling_factor,
            fy=scaling_factor,
            interpolation=cv2.INTER_AREA,
        )
        gsframe = cv2.resize(
            gsframe,
            None,
            fx=scaling_factor,
            fy=scaling_factor,
            interpolation=cv2.INTER_AREA,
        )
        raw_scan_frame = cv2.resize(
            raw_scan_frame,
            None,
            fx=scaling_factor,
            fy=scaling_factor,
            interpolation=cv2.INTER_AREA,
        )

    if rotate == 1:
        if frames % 3 == 1:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_COUNTERCLOCKWISE)
            raw_scan_frame = cv2.rotate(raw_scan_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if frames % 3 == 2:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_CLOCKWISE)
            raw_scan_frame = cv2.rotate(raw_scan_frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotate == 2:
        if frames % 2 == 0:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_COUNTERCLOCKWISE)
            raw_scan_frame = cv2.rotate(raw_scan_frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_CLOCKWISE)
            raw_scan_frame = cv2.rotate(raw_scan_frame, cv2.ROTATE_90_CLOCKWISE)

    face_locations = face_backend.detect(frame, gsframe)
    logger.debug("Frame %d: detected %d face(s)", frames, len(face_locations))

    if not face_locations:
        backlit_scene = is_backlit_scene(raw_scan_frame)
        if backlit_scene:
            send_to_ui("M", _("Backlit scene, adjusting exposure"))
            try:
                bracket = video_capture.advance_exposure_bracket()
                logger.debug("Frame %d: exposure bracket result=%s", frames, bracket)
            except (CameraHelperTimeout, RuntimeError) as err:
                logger.debug("Frame %d: exposure bracket unavailable: %s", frames, err)
        if is_unlit_frame(raw_gsframe, unlit_threshold):
            dark_tries += 1
            dark_running_total += metrics["dark_percent"]
            send_to_ui("S", format_scan_status(frames, black_tries, dark_tries))
        elif not backlit_scene:
            send_to_ui("M", _("Look at the camera"))

    for face_location in face_locations:
        lighting = classify_face_lighting(raw_scan_frame, face_location, dark_threshold=dark_threshold)
        logger.debug(
            "Frame %d: face_lighting=%s face_dark=%.1f%% face_p95=%.1f global_p95=%.1f",
            frames,
            lighting["state"],
            lighting["face"]["dark_percent"],
            lighting["face"]["p95"],
            lighting["global"]["p95"],
        )
        if lighting["face_dark"]:
            dark_tries += 1
            dark_running_total += lighting["face"]["dark_percent"]
            send_to_ui("S", format_scan_status(frames, black_tries, dark_tries))
            send_to_ui(
                "M",
                _("Face is underexposed") if not lighting["backlit"] else _("Face is backlit"),
            )
            try:
                tuning = video_capture.tune_for_dark_face(backlit=lighting["backlit"])
                logger.debug("Frame %d: camera tuning result=%s", frames, tuning)
            except (CameraHelperTimeout, RuntimeError) as err:
                logger.debug("Frame %d: camera tuning unavailable: %s", frames, err)

        face_encoding = face_backend.encode(frame, face_location)
        match_index, match = face_backend.match(encodings, face_encoding)

        if match is None:
            continue

        if best_score < match:
            best_score = match

        logger.debug(
            "Frame %d: best match score=%.3f (threshold=%.3f)",
            frames,
            match,
            face_backend.match_threshold,
        )

        if face_backend.is_match(match):
            timings["tt"] = time.time() - timings["st"]
            timings["fl"] = time.time() - timings["fr"]

            logger.info(
                'Face matched model "%s" with score %.3f in %.2fs',
                labels[match_index]["label"],
                match,
                timings["fl"],
            )

            if end_report:
                print_end_report(match, match_index, labels, frame)

            if save_successful:
                make_snapshot(_("SUCCESSFUL"))

            if config.getboolean("rubberstamps", "enabled", fallback=False):
                print(_("Rubberstamps are not supported by the opencv_sface backend yet"))
                logger.error("Rubberstamps requested with unsupported backend")
                exit(15)

            release_video_capture()

            if not request_ui_confirmation():
                exit(15)

            exit(0)
