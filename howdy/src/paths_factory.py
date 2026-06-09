from pathlib import PurePath
import paths

models = [
    "shape_predictor_5_face_landmarks.dat",
    "mmod_human_face_detector.dat",
    "dlib_face_recognition_resnet_model_v1.dat",
]

opencv_sface_models = [
    "face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx",
]


def validate_username(user: str) -> str:
    """Return a safe username for model-file lookup."""
    if not isinstance(user, str) or user in {"", ".", ".."}:
        raise ValueError("Invalid username")

    if any(ord(char) < 32 or ord(char) == 127 for char in user):
        raise ValueError("Invalid username")

    if "/" in user or "\\" in user:
        raise ValueError("Invalid username")

    if PurePath(user).name != user:
        raise ValueError("Invalid username")

    return user


def dlib_data_dir_path() -> str:
    return str(paths.dlib_data_dir)


def shape_predictor_5_face_landmarks_path() -> str:
    return str(paths.dlib_data_dir / models[0])


def mmod_human_face_detector_path() -> str:
    return str(paths.dlib_data_dir / models[1])


def dlib_face_recognition_resnet_model_v1_path() -> str:
    return str(paths.dlib_data_dir / models[2])


def face_data_dir_path() -> str:
    return str(paths.face_data_dir)


def face_detection_yunet_path() -> str:
    return str(paths.face_data_dir / opencv_sface_models[0])


def face_recognition_sface_path() -> str:
    return str(paths.face_data_dir / opencv_sface_models[1])


def user_model_path(user: str) -> str:
    validate_username(user)
    return str(paths.user_models_dir / f"{user}.dat")


def config_file_path() -> str:
    return str(paths.config_dir / "config.ini")


def snapshots_dir_path() -> PurePath:
    return paths.log_path / "snapshots"


def snapshot_path(snapshot: str) -> str:
    return str(snapshots_dir_path() / snapshot)


def user_models_dir_path() -> PurePath:
    return paths.user_models_dir


def logo_path() -> str:
    return str(paths.data_dir / "logo.png")


def gtk_bin_path() -> str:
    return str(getattr(paths, "gtk_bin_path", PurePath("/usr/bin/howdy-gtk")))
