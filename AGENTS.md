# Repository Guidelines

## Project Shape

This fork modernizes Howdy for current Ubuntu/Debian systems. Runtime face
recognition uses OpenCV YuNet/SFace ONNX models; dlib assets are kept only as
legacy data.

- `howdy/src/`: CLI, PAM compare flow, recorders, face backends, config.
- `howdy/src/face_backends/opencv_sface.py`: OpenCV YuNet/SFace backend.
- `howdy/src/recorders/video_capture.py`: camera selection, V4L capture, cached
  auto-detection.
- `howdy/src/pam/`: C++ PAM module.
- `howdy-gtk/src/`: GTK helper UI.
- `dist/` and `build/`: generated local build/package output.

## Build And Verify

Preferred quick checks:

```bash
python3 -m py_compile howdy/src/recorders/video_capture.py howdy/src/compare.py howdy/src/cli/test.py howdy-gtk/src/tab_video.py
meson compile -C build
```

For package validation, build a `.deb` using the one-shot flow in `README.md`,
then run:

```bash
apt install --simulate ./dist/howdy-opencv-sface_<version>_amd64.deb
```

Manual validation needs real hardware:

```bash
sudo howdy add
sudo howdy test
sudo su -
```

## Implementation Rules

- Keep the installed runtime layout compatible with Debian/Ubuntu PAM:
  `/lib/security`, `/etc/howdy`, `/var/log/howdy`, `/var/cache/howdy`.
- Do not reintroduce a runtime dependency on dlib. If touching legacy dlib data,
  keep it isolated from the default OpenCV backend.
- Be conservative around PAM code. Avoid blocking waits in timeout paths and
  avoid changes that can hang `sudo`, `su`, login, or lock-screen auth.
- Keep camera auto-detection quiet during normal PAM auth. Use the cached device
  first and scan only when the cached or configured camera cannot be opened.
- GTK preview should remain simple GLib/GTK code; do not add asyncio unless the
  event-loop integration is explicit and tested.
- Do not commit generated build output from `build/` or `dist/`.

## Packaging Notes

The local package intentionally conflicts/replaces `howdy-gtk` and provides a
single `howdy` package containing the CLI, PAM module, GTK helper, config, and
OpenCV models.

When changing installed paths, update:

- `meson.options`
- generated path configuration under `howdy/src` and `howdy-gtk/src`
- README package build block
- Debian maintainer scripts in the package build flow
