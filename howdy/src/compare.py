# Compare incoming video with known faces
# Running in a local python instance to get around PATH issues

import atexit
import configparser
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import cv2
import numpy as np

import paths_factory
import snapshot
from face_backends import load_face_backend
from i18n import _
from recorders.video_capture import VideoCapture


def setup_logger():
    log_dir = "/var/log/howdy"
    try:
        os.makedirs(log_dir, exist_ok=True)
        logging.basicConfig(
            filename=os.path.join(log_dir, "compare.log"),
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
    except PermissionError:
        logging.basicConfig(level=logging.CRITICAL)

    return logging.getLogger("howdy.compare")


logger = setup_logger()
timings = {"st": time.time()}
DEFAULT_TIMEOUT = 10


def exit(code: int | None = None) -> None:
    """Exit while closing howdy-gtk properly"""
    global gtk_proc

    if "gtk_proc" in globals() and gtk_proc is not None:
        try:
            gtk_proc.terminate()
        except Exception as err:
            logger.warning("Failed to terminate gtk_proc: %s", err)

    if code is not None:
        sys.exit(code)


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
except FileNotFoundError:
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

dark_threshold = config.getfloat("video", "dark_threshold", fallback=50.0)
end_report = config.getboolean("debug", "end_report", fallback=False)
save_failed = config.getboolean("snapshots", "save_failed", fallback=False)
save_successful = config.getboolean("snapshots", "save_successful", fallback=False)
gtk_stdout = config.getboolean("debug", "gtk_stdout", fallback=False)
rotate = config.getint("video", "rotate", fallback=0)

gtk_pipe = sys.stdout if gtk_stdout else subprocess.DEVNULL

try:
    gtk_proc = subprocess.Popen(
        ["howdy-gtk", "--start-auth-ui"],
        stdin=subprocess.PIPE,
        stdout=gtk_pipe,
        stderr=gtk_pipe,
        start_new_session=True,
    )
    atexit.register(exit)
except FileNotFoundError:
    pass

send_to_ui("M", _("Starting up..."))

timings["in"] = time.time() - timings["st"]
logger.info("Face backend %s initialized", face_backend.name)

timings["ic"] = time.time()
logger.info("Opening video capture device")
video_capture = VideoCapture(config)
logger.info("Video capture opened successfully")
exposure = config.getint("video", "exposure", fallback=-1)
timings["ic"] = time.time() - timings["ic"]
logger.info("Camera opened in %.2fs", timings["ic"])

max_height = config.getfloat("video", "max_height", fallback=320.0)
height = video_capture.internal.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1
if rotate == 2:
    height = video_capture.internal.get(cv2.CAP_PROP_FRAME_WIDTH) or 1
scaling_factor = (max_height / height) or 1

timeout = config.getint("video", "timeout", fallback=DEFAULT_TIMEOUT)
dark_threshold = config.getfloat("video", "dark_threshold", fallback=60)
end_report = config.getboolean("debug", "end_report", fallback=False)

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

send_to_ui("M", _("Identifying you..."))

valid_frames = 0
timings["fr"] = time.time()
dark_running_total = 0

while True:
    frames += 1

    ui_subtext = "Scanned " + str(valid_frames - dark_tries) + " frames"
    if dark_tries > 1:
        ui_subtext += " (skipped " + str(dark_tries) + " dark frames)"
    send_to_ui("S", ui_subtext)

    elapsed = time.time() - timings["fr"]
    if elapsed > timeout:
        if save_failed:
            make_snapshot(_("FAILED"))

        logger.error(
            "Timeout reached after %.2fs, scanned %d frames (%d valid, %d dark)",
            elapsed,
            frames,
            valid_frames,
            dark_tries,
        )

        if dark_tries == valid_frames:
            print(_("All frames were too dark, please check dark_threshold in config"))
            print(
                _("Average darkness: {avg}, Threshold: {threshold}").format(
                    avg=str(dark_running_total / max(1, valid_frames)),
                    threshold=str(dark_threshold),
                )
            )
            exit(13)

        exit(11)

    frame, gsframe = video_capture.read_frame()
    gsframe = clahe.apply(gsframe)

    if save_failed or save_successful:
        if len(snapframes) < 3:
            snapframes.append(frame)

    hist = cv2.calcHist([gsframe], [0], None, [8], [0, 256])
    hist_total = np.sum(hist)
    darkness = float(hist[0][0] / hist_total * 100)

    logger.debug(
        "Frame %d: darkness=%.1f%%, valid_frames=%d, dark_tries=%d",
        frames,
        darkness,
        valid_frames,
        dark_tries,
    )

    if (hist_total == 0) or (darkness == 100):
        black_tries += 1
        continue

    dark_running_total += darkness
    valid_frames += 1

    if darkness > dark_threshold:
        dark_tries += 1
        continue

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

    if rotate == 1:
        if frames % 3 == 1:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if frames % 3 == 2:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_CLOCKWISE)
    elif rotate == 2:
        if frames % 2 == 0:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            gsframe = cv2.rotate(gsframe, cv2.ROTATE_90_CLOCKWISE)

    face_locations = face_backend.detect(frame, gsframe)
    logger.debug("Frame %d: detected %d face(s)", frames, len(face_locations))

    for face_location in face_locations:
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

            logger.info("Face matched with score %.3f in %.2fs", match, timings["fl"])

            if end_report:
                print_end_report(match, match_index, labels, frame)

            if save_successful:
                make_snapshot(_("SUCCESSFUL"))

            if config.getboolean("rubberstamps", "enabled", fallback=False):
                print(_("Rubberstamps are not supported by the opencv_sface backend yet"))
                logger.error("Rubberstamps requested with unsupported backend")
                exit(15)

            exit(0)

    if exposure != -1:
        video_capture.internal.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1.0)
        video_capture.internal.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
