# Save the face of the user in encoded form

# Import required modules
import time
import os
import sys
import json
import configparser
import builtins
import subprocess
import paths_factory
import lockscreen_permissions

from face_backends import load_face_backend
from frame_quality import is_black_frame, is_face_too_dark, is_unlit_frame, light_metrics
from recorders.video_capture import VideoCapture
from i18n import _

import cv2

# Read config from disk
config = configparser.ConfigParser()
config.read(paths_factory.config_file_path())

try:
	face_backend = load_face_backend(config)
except (FileNotFoundError, ValueError) as err:
	print(err)
	sys.exit(1)

user = builtins.howdy_user
# The permanent file to store the encoded model in
enc_file = paths_factory.user_model_path(user)
# Known encodings
encodings = []

# Make the ./models folder if it doesn't already exist
if not os.path.exists(paths_factory.user_models_dir_path()):
	print(_("No face model folder found, creating one"))
	os.makedirs(paths_factory.user_models_dir_path())

# To try read a premade encodings file if it exists
try:
	encodings = json.load(open(enc_file))
except FileNotFoundError:
	encodings = []

# Print a warning if too many encodings are being added
if len(encodings) > 3:
	print(_("NOTICE: Each additional model slows down the face recognition engine slightly"))
	print(_("Press Ctrl+C to cancel\n"))

# Make clear what we are doing if not human
if not builtins.howdy_args.plain:
	print(_("Adding face model for the user ") + user)

# Set the default label
label = "Initial model"

# some id's can be skipped, but the last id is always the maximum
next_id = encodings[-1]["id"] + 1 if encodings else 0

# Get the label from the cli arguments if provided
if builtins.howdy_args.arguments:
	label = builtins.howdy_args.arguments[0]

# Or set the default label
else:
	label = _("Model #") + str(next_id)

# Keep de default name if we can't ask questions
if builtins.howdy_args.y:
	print(_('Using default label "%s" because of -y flag') % (label, ))
else:
	# Ask the user for a custom label
	label_in = input(_("Enter a label for this new model [{}]: ").format(label))

	# Set the custom label (if any) and limit it to 24 characters
	if label_in != "":
		label = label_in[:24]

# Remove illegal characters
if "," in label:
	print(_("NOTICE: Removing illegal character \",\" from model name"))
	label = label.replace(",", "")

# Prepare the metadata for insertion
insert_model = {
	"time": int(time.time()),
	"label": label,
	"id": next_id,
	"backend": face_backend.name,
	"embedding_version": face_backend.embedding_version,
	"distance_metric": face_backend.distance_metric,
	"data": []
}

# Set up video_capture
video_capture = VideoCapture(config)

print(_("\nPlease look straight into the camera"))

# Give the user time to read
time.sleep(2)

# Will contain found face encodings
enc = []
# Count the number of read frames
frames = 0
# Count the number of illuminated read frames
valid_frames = 0
# Count the number of illuminated frames that
# were rejected for being too dark
dark_tries = 0
# Track the running darkness total
dark_running_total = 0
face_locations = None
accepted_face_location = None

dark_threshold = config.getfloat("video", "dark_threshold", fallback=60)
unlit_threshold = config.getfloat("video", "unlit_threshold", fallback=24.0)

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

# Loop through frames till we hit a timeout
while frames < 60:
	frames += 1
	# Grab a single frame of video
	frame, gsframe = video_capture.read_frame()
	gsframe = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
	raw_gsframe = gsframe

	metrics = light_metrics(raw_gsframe)

	if is_black_frame(raw_gsframe):
		continue

	if is_unlit_frame(raw_gsframe, unlit_threshold):
		dark_running_total += metrics["dark_percent"]
		dark_tries += 1
		continue

	valid_frames += 1
	gsframe = clahe.apply(raw_gsframe)

	# Get all faces from that frame as encodings
	face_locations = face_backend.detect(frame, gsframe)

	# If we've found at least one, we can continue
	if face_locations:
		if len(face_locations) == 1 and is_face_too_dark(gsframe, face_locations[0], dark_threshold):
			dark_running_total += light_metrics(gsframe)["dark_percent"]
			dark_tries += 1
			face_locations = None
			continue
		accepted_face_location = face_locations[0]
		break

video_capture.release()

# If we've found no faces, try to determine why
if not face_locations:
	if valid_frames == 0:
		print(_("Camera saw only black frames - is IR emitter working?"))
	elif dark_tries > 0:
		print(_("All frames were too dark, please check IR emitter, device_fps, unlit_threshold or dark_threshold in config"))
		print(_("Average darkness: {avg}, Threshold: {threshold}").format(avg=str(dark_running_total / dark_tries), threshold=str(dark_threshold)))
	else:
		print(_("No face detected, aborting"))
	sys.exit(1)

# If more than 1 faces are detected we can't know which one belongs to the user
elif len(face_locations) > 1:
	print(_("Multiple faces detected, aborting"))
	sys.exit(1)

face_location = accepted_face_location or face_locations[0]

# Get the encodings in the frame
face_encoding = face_backend.encode(frame, face_location)

insert_model["data"].append(face_encoding.tolist())

# Insert full object into the list
encodings.append(insert_model)

# Save the new encodings to disk
with open(enc_file, "w") as datafile:
	json.dump(encodings, datafile)

try:
	lockscreen_permissions.grant_lockscreen_model_access(user, enc_file)
except (KeyError, OSError, subprocess.SubprocessError):
	print(_("NOTICE: Could not grant KDE lockscreen read access to the face model"))

# Give let the user know how it went
print(_("""\nScan complete
Added a new model to """) + user)
