from .opencv_sface import OpenCVSFaceBackend


DEFAULT_BACKEND = "opencv_sface"


def selected_backend_name(config) -> str:
    return config.get("core", "face_backend", fallback=DEFAULT_BACKEND).strip()


def load_face_backend(config):
    backend_name = selected_backend_name(config)

    if backend_name == "opencv_sface":
        backend = OpenCVSFaceBackend(config)
        backend.load()
        return backend

    raise ValueError(
        "Unsupported face backend '{}'. Available backends: opencv_sface".format(
            backend_name
        )
    )
