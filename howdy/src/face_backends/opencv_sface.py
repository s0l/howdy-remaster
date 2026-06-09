import os

import cv2
import numpy as np

import paths_factory


class OpenCVSFaceBackend:
    name = "opencv_sface"
    embedding_version = "opencv_zoo_sface_2021dec"
    distance_metric = "cosine_similarity"

    def __init__(self, config):
        self.config = config
        self.detector = None
        self.recognizer = None
        self.detector_model = self._path_option(
            "detector_model", paths_factory.face_detection_yunet_path()
        )
        self.recognizer_model = self._path_option(
            "recognizer_model", paths_factory.face_recognition_sface_path()
        )
        self.score_threshold = config.getfloat(
            "opencv_sface", "detector_score_threshold", fallback=0.9
        )
        self.nms_threshold = config.getfloat(
            "opencv_sface", "detector_nms_threshold", fallback=0.3
        )
        self.top_k = config.getint("opencv_sface", "detector_top_k", fallback=5000)
        self.match_threshold = config.getfloat(
            "opencv_sface", "match_threshold", fallback=0.363
        )

    def _path_option(self, option, fallback):
        value = self.config.get("opencv_sface", option, fallback=fallback).strip()
        return value or fallback

    def load(self) -> None:
        missing = [
            path
            for path in [self.detector_model, self.recognizer_model]
            if not os.path.isfile(path)
        ]
        if missing:
            raise FileNotFoundError(
                "Face model files are missing: {}. Run install.sh in {}".format(
                    ", ".join(missing), paths_factory.face_data_dir_path()
                )
            )

        self.detector = cv2.FaceDetectorYN.create(
            self.detector_model,
            "",
            (320, 320),
            self.score_threshold,
            self.nms_threshold,
            self.top_k,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(self.recognizer_model, "")

    def prepare_frame(self, frame, gray_frame=None):
        if frame is None:
            return None

        if len(frame.shape) == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        if len(frame.shape) == 3 and frame.shape[2] == 1:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

        return frame

    def detect(self, frame, gray_frame=None):
        input_frame = self.prepare_frame(frame, gray_frame)
        if input_frame is None:
            return []

        height, width = input_frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(input_frame)

        if faces is None:
            return []

        return list(faces)

    def encode(self, frame, face):
        input_frame = self.prepare_frame(frame)
        aligned_face = self.recognizer.alignCrop(input_frame, face)
        feature = self.recognizer.feature(aligned_face)
        return np.asarray(feature, dtype=np.float32).flatten()

    def match(self, known_encodings, candidate_encoding):
        if len(known_encodings) == 0:
            return None, None

        candidate = np.asarray(candidate_encoding, dtype=np.float32)
        known = np.asarray(known_encodings, dtype=np.float32)
        candidate_norm = np.linalg.norm(candidate)
        known_norms = np.linalg.norm(known, axis=1)
        denom = np.maximum(known_norms * candidate_norm, 1e-12)
        scores = np.dot(known, candidate) / denom
        best_index = int(np.argmax(scores))
        return best_index, float(scores[best_index])

    def is_match(self, score) -> bool:
        return score is not None and score >= self.match_threshold

    def face_rect(self, face):
        x, y, width, height = face[:4]
        return int(x), int(y), int(width), int(height)
