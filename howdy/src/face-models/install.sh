#!/bin/sh
set -eu

if command -v wget >/dev/null 2>&1; then
	wget --tries 5 --output-document face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
	wget --tries 5 --output-document face_recognition_sface_2021dec.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
elif command -v curl >/dev/null 2>&1; then
	curl --location --retry 5 --output face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
	curl --location --retry 5 --output face_recognition_sface_2021dec.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
else
	echo "Please install wget or curl to download the OpenCV face model files." >&2
	exit 1
fi
