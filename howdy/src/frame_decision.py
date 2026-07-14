"""Windowed frame decisions for camera tuning."""

from collections import deque


DEFAULT_FRAME_DECISION_WINDOW = 3
MAX_FRAME_DECISION_WINDOW = 10
HIGH_DARK_PERCENT_THRESHOLD = 85.0


def clamp_decision_window(value):
	try:
		value = int(value)
	except (TypeError, ValueError):
		value = DEFAULT_FRAME_DECISION_WINDOW

	return max(1, min(MAX_FRAME_DECISION_WINDOW, value))


class FrameDecisionWindow:
	def __init__(self, size=DEFAULT_FRAME_DECISION_WINDOW):
		self.size = clamp_decision_window(size)
		self.frames = deque(maxlen=self.size)

	def add(
		self,
		*,
		black=False,
		unlit=False,
		dark_percent=0.0,
		p95=0.0,
		face_count=0,
		backlit=False,
		face_dark=False,
	):
		entry = {
			"black": bool(black),
			"unlit": bool(unlit),
			"dark_percent": float(dark_percent),
			"p95": float(p95),
			"face_count": int(face_count or 0),
			"backlit": bool(backlit),
			"face_dark": bool(face_dark),
		}
		self.frames.append(entry)
		return entry

	def ready(self):
		return len(self.frames) >= self.size

	def _majority(self):
		return self.size // 2 + 1

	def summary(self):
		frames = list(self.frames)
		face_frames = sum(1 for frame in frames if frame["face_count"] > 0)
		high_dark_no_face = sum(
			1
			for frame in frames
			if frame["face_count"] == 0
			and frame["dark_percent"] >= HIGH_DARK_PERCENT_THRESHOLD
		)
		usable_face_frames = sum(
			1
			for frame in frames
			if frame["face_count"] > 0
			and not frame["black"]
			and not frame["unlit"]
		)

		return {
			"size": self.size,
			"frames": len(frames),
			"ready": self.ready(),
			"black": sum(1 for frame in frames if frame["black"]),
			"unlit": sum(1 for frame in frames if frame["unlit"]),
			"face": face_frames,
			"no_face": len(frames) - face_frames,
			"backlit_no_face": sum(
				1
				for frame in frames
				if frame["face_count"] == 0 and frame["backlit"]
			),
			"face_dark": sum(
				1
				for frame in frames
				if frame["face_count"] > 0 and frame["face_dark"]
			),
			"high_dark_no_face": high_dark_no_face,
			"alternating_dark": high_dark_no_face > 0 and usable_face_frames > 0,
		}

	def stable_face_dark(self):
		summary = self.summary()
		return (
			summary["ready"]
			and summary["face_dark"] >= self._majority()
			and summary["face_dark"] == summary["face"]
		)

	def stable_no_face_backlit(self):
		summary = self.summary()
		return (
			summary["ready"]
			and summary["face"] == 0
			and summary["backlit_no_face"] >= self._majority()
		)

	def stable_bad_stream(self):
		summary = self.summary()
		return (
			summary["ready"]
			and summary["face"] == 0
			and summary["black"] + summary["unlit"] >= self._majority()
		)

	def alternating_bad_frames(self):
		return self.summary()["alternating_dark"]
