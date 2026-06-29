"""Frame brightness helpers for IR camera streams."""

import numpy as np


DEFAULT_UNLIT_P95_THRESHOLD = 24.0
BLACK_P95_THRESHOLD = 1.0
DEFAULT_FACE_DARK_THRESHOLD = 65.0
BACKLIGHT_P95_THRESHOLD = 180.0
BACKLIGHT_DARK_PERCENT_THRESHOLD = 45.0
BACKLIGHT_DYNAMIC_RANGE_THRESHOLD = 120.0


def light_metrics(gray_frame):
	if gray_frame is None:
		return {"pixels": 0, "dark_percent": 100.0, "p95": 0.0}

	values = np.asarray(gray_frame, dtype=np.uint8).reshape(-1)
	if values.size == 0:
		return {"pixels": 0, "dark_percent": 100.0, "p95": 0.0}

	return {
		"pixels": int(values.size),
		"dark_percent": float(np.count_nonzero(values < 32) / values.size * 100),
		"p10": float(np.percentile(values, 10)),
		"p95": float(np.percentile(values, 95)),
	}


def is_black_frame(gray_frame):
	metrics = light_metrics(gray_frame)
	return metrics["pixels"] == 0 or metrics["p95"] <= BLACK_P95_THRESHOLD


def is_unlit_frame(gray_frame, p95_threshold=DEFAULT_UNLIT_P95_THRESHOLD):
	metrics = light_metrics(gray_frame)
	return metrics["pixels"] == 0 or metrics["p95"] <= p95_threshold


def face_region(gray_frame, face, padding=0.15):
	if gray_frame is None:
		return None

	height, width = gray_frame.shape[:2]
	x, y, face_width, face_height = [float(value) for value in face[:4]]
	pad_x = face_width * padding
	pad_y = face_height * padding

	left = max(0, int(x - pad_x))
	top = max(0, int(y - pad_y))
	right = min(width, int(x + face_width + pad_x))
	bottom = min(height, int(y + face_height + pad_y))

	if right <= left or bottom <= top:
		return None

	return gray_frame[top:bottom, left:right]


def is_face_too_dark(gray_frame, face, dark_threshold):
	roi = face_region(gray_frame, face)
	if roi is None:
		return True

	return light_metrics(roi)["dark_percent"] > dark_threshold


def face_light_metrics(gray_frame, face):
	roi = face_region(gray_frame, face)
	if roi is None:
		return {"pixels": 0, "dark_percent": 100.0, "p95": 0.0}

	return light_metrics(roi)


def classify_face_lighting(gray_frame, face, dark_threshold=DEFAULT_FACE_DARK_THRESHOLD):
	global_metrics = light_metrics(gray_frame)
	face_metrics = face_light_metrics(gray_frame, face)
	face_dark = face_metrics["dark_percent"] > dark_threshold
	backlit = face_dark and global_metrics["p95"] >= BACKLIGHT_P95_THRESHOLD

	if backlit:
		state = "backlit"
	elif face_dark:
		state = "face_dark"
	else:
		state = "good"

	return {
		"state": state,
		"face_dark": face_dark,
		"backlit": backlit,
		"global": global_metrics,
		"face": face_metrics,
	}


def is_backlit_scene(gray_frame):
	metrics = light_metrics(gray_frame)
	dynamic_range = metrics["p95"] - metrics["p10"]

	return (
		metrics["dark_percent"] >= BACKLIGHT_DARK_PERCENT_THRESHOLD
		and metrics["p95"] >= BACKLIGHT_P95_THRESHOLD
		and dynamic_range >= BACKLIGHT_DYNAMIC_RANGE_THRESHOLD
	)
