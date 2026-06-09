# Top level class for a video capture providing simplified API's for common
# functions

# Import required modules
import configparser
import cv2
import glob
import os
import sys

from i18n import _

AUTO_DEVICE_PATHS = {"", "none", "auto"}
DEVICE_CACHE_PATH = "/var/cache/howdy/device_path"


def _video_device_name(path):
	real_path = os.path.realpath(path)
	device = os.path.basename(real_path)
	name_path = os.path.join("/sys/class/video4linux", device, "name")

	try:
		with open(name_path) as name_file:
			return name_file.read().strip()
	except OSError:
		return ""


def opencv_capture_source(path):
	real_path = os.path.realpath(path)
	device = os.path.basename(real_path)

	if device.startswith("video") and device[5:].isdigit():
		return int(device[5:])

	return path


def _open_opencv_capture(path, quiet=False):
	previous_log_level = None

	if quiet and hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
		previous_log_level = cv2.getLogLevel()
		cv2.setLogLevel(0)

	try:
		return cv2.VideoCapture(opencv_capture_source(path), cv2.CAP_V4L)
	finally:
		if previous_log_level is not None:
			cv2.setLogLevel(previous_log_level)


def _camera_can_open(path):
	if not os.path.exists(path):
		return False

	capture = _open_opencv_capture(path, quiet=True)
	opened = capture.isOpened()
	capture.release()

	return opened


def _read_cached_device_path():
	try:
		with open(DEVICE_CACHE_PATH) as cache_file:
			path = cache_file.read().strip()
	except OSError:
		return None

	return path or None


def _write_cached_device_path(path):
	try:
		os.makedirs(os.path.dirname(DEVICE_CACHE_PATH), exist_ok=True)
		with open(DEVICE_CACHE_PATH, "w") as cache_file:
			cache_file.write(path + "\n")
	except OSError:
		pass


def _is_gray_frame(frame):
	if frame is None or len(frame.shape) < 3:
		return True

	return bool((frame[:, :, 0] == frame[:, :, 1]).all() and (frame[:, :, 1] == frame[:, :, 2]).all())


def _score_device(path, probe=True):
	name = _video_device_name(path)
	search_text = (path + " " + name).lower()
	score = 0

	if "infrared" in search_text or " ir " in " " + search_text + " ":
		score += 100
	if "depth" in search_text:
		score += 60
	if "camera" in search_text or "webcam" in search_text or "cam" in search_text:
		score += 20
	if "/dev/v4l/by-path/" in path or "/dev/v4l/by-id/" in path:
		score += 10
	if "metadata" in search_text:
		score -= 100

	if not probe:
		return score, name

	capture = _open_opencv_capture(path, quiet=True)
	if not capture.isOpened():
		capture.release()
		return score - 1000, name

	ret, frame = capture.read()
	capture.release()
	if not ret:
		return score - 500, name

	if _is_gray_frame(frame):
		score += 30

	return score, name


def discover_camera_devices(probe=True):
	"""Return camera candidates sorted by likely usefulness for Howdy."""
	paths = []
	for pattern in [
		"/dev/v4l/by-path/*",
		"/dev/v4l/by-id/*",
		"/dev/video*",
	]:
		paths.extend(glob.glob(pattern))

	for sysfs_path in glob.glob("/sys/class/video4linux/video*"):
		paths.append("/dev/" + os.path.basename(sysfs_path))

	candidates = {}
	for path in sorted(paths):
		sysfs_name_path = os.path.join(
			"/sys/class/video4linux", os.path.basename(path), "name"
		)
		if not os.path.exists(path) and not os.path.exists(sysfs_name_path):
			continue

		real_path = os.path.realpath(path)
		score, name = _score_device(path, probe=probe)
		current = candidates.get(real_path)

		if current is None or score > current["score"]:
			candidates[real_path] = {
				"path": path,
				"real_path": real_path,
				"name": name,
				"score": score,
			}

	return sorted(candidates.values(), key=lambda candidate: (-candidate["score"], candidate["path"]))


def resolve_device_path(config, warn=True):
	configured_path = config.get("video", "device_path", fallback="none").strip()

	if configured_path.lower() not in AUTO_DEVICE_PATHS and os.path.exists(configured_path):
		return configured_path

	cached_path = _read_cached_device_path()
	if configured_path.lower() in AUTO_DEVICE_PATHS and cached_path and _camera_can_open(cached_path):
		return cached_path

	candidates = [
		candidate for candidate in discover_camera_devices(probe=True)
		if candidate["score"] > -100
	]
	probed = True

	if not candidates:
		candidates = discover_camera_devices(probe=False)
		probed = False

	if candidates:
		selected = candidates[0]
		_write_cached_device_path(selected["path"])
		if warn:
			if configured_path.lower() not in AUTO_DEVICE_PATHS:
				print(_("Configured camera path was not found, falling back to auto-detected camera:"))
				print("\t{} ({})".format(selected["path"], selected["name"] or selected["real_path"]))
			if not probed:
				print(_("Warning: Howdy could not probe camera devices before selecting one."))
		return selected["path"]

	if warn:
		print(_("Howdy could not find a camera device at the path specified in the config file."))
		print(_("It is very likely that the path is not configured correctly, please edit the 'device_path' config value by running:"))
		print("\n\tsudo howdy config\n")

	sys.exit(14)

# Class to provide boilerplate code to build a video recorder with the
# correct settings from the config file.
#
# The internal recorder can be accessed with 'video_capture.internal'


class VideoCapture:
	def __init__(self, config):
		"""
		Creates a new VideoCapture instance depending on the settings in the
		provided config file.

		Config can either be a string to the path, or a pre-setup configparser.
		"""

		# Parse config from string if needed
		if isinstance(config, str):
			self.config = configparser.ConfigParser()
			self.config.read(config)
		else:
			self.config = config

		self.device_path = resolve_device_path(
			self.config,
			warn=self.config.getboolean("video", "warn_no_device", fallback=True),
		)

		# Create reader
		# The internal video recorder
		self.internal = None
		# The frame width
		self.fw = None
		# The frame height
		self.fh = None
		self._create_reader()

		if hasattr(self.internal, "isOpened") and not self.internal.isOpened():
			print(_("Howdy selected a camera device but could not open it:"))
			print("\t" + self.device_path)
			sys.exit(14)

		# Request a frame to wake the camera up
		self.internal.grab()

	def __del__(self):
		"""
		Frees resources when destroyed
		"""
		if self is not None:
			try:
				self.internal.release()
			except AttributeError as err:
				pass

	def release(self):
		"""
		Release cameras
		"""
		if self is not None:
			self.internal.release()

	def read_frame(self):
		"""
		Reads a frame, returns the frame and an attempted grayscale conversion of
		the frame in a tuple:

		(frame, grayscale_frame)

		If the grayscale conversion fails, both items in the tuple are identical.
		"""

		# Grab a single frame of video
		# Don't remove ret, it doesn't work without it
		ret, frame = self.internal.read()
		if not ret:
			print(_("Failed to read camera specified in the 'device_path' config option, aborting"))
			sys.exit(14)

		try:
			# Convert from color to grayscale
			# First processing of frame, so frame errors show up here
			gsframe = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
		except RuntimeError:
			gsframe = frame
		except cv2.error:
			print("\nAn error occurred in OpenCV\n")
			raise
		return frame, gsframe

	def _create_reader(self):
		"""
		Sets up the video reader instance
		"""
		recording_plugin = self.config.get("video", "recording_plugin", fallback="opencv")

		if recording_plugin == "ffmpeg":
			# Set the capture source for ffmpeg
			from recorders.ffmpeg_reader import ffmpeg_reader
			self.internal = ffmpeg_reader(
				self.device_path,
				self.config.get("video", "device_format", fallback="v4l2")
			)

		elif recording_plugin == "pyv4l2":
			# Set the capture source for pyv4l2
			from recorders.pyv4l2_reader import pyv4l2_reader
			self.internal = pyv4l2_reader(
				self.device_path,
				self.config.get("video", "device_format", fallback="v4l2")
			)

		else:
			# Start video capture on the IR camera through OpenCV
			self.internal = _open_opencv_capture(self.device_path)
			# Set the capture frame rate
			# Without this the first detected (and possibly lower) frame rate is used, -1 seems to select the highest
			# Use 0 as a fallback to avoid breaking an existing setup, new installs should default to -1
			self.fps = self.config.getint("video", "device_fps", fallback=0)
			if self.fps != 0:
				self.internal.set(cv2.CAP_PROP_FPS, self.fps)

		# Force MJPEG decoding if true
		if self.config.getboolean("video", "force_mjpeg", fallback=False):
			# Set a magic number, will enable MJPEG but is badly documentated
			self.internal.set(cv2.CAP_PROP_FOURCC, 1196444237)

		# Set the frame width and height if requested
		self.fw = self.config.getint("video", "frame_width", fallback=-1)
		self.fh = self.config.getint("video", "frame_height", fallback=-1)
		if self.fw != -1:
			self.internal.set(cv2.CAP_PROP_FRAME_WIDTH, self.fw)
		if self.fh != -1:
			self.internal.set(cv2.CAP_PROP_FRAME_HEIGHT, self.fh)
