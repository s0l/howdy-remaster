# Repository Guidelines

## Project Shape

This fork modernizes Howdy for current Ubuntu/Debian systems. Runtime face
recognition uses OpenCV YuNet/SFace ONNX models; dlib assets are kept only as
legacy data.

- `howdy/src/`: CLI, PAM compare flow, recorders, face backends, config.
- `howdy/src/face_backends/opencv_sface.py`: OpenCV YuNet/SFace backend.
- `howdy/src/recorders/video_capture.py`: camera selection, V4L capture, cached
  auto-detection.
- `VERSION`: repository package version used by `scripts/build-deb.sh`.
- `scripts/build-deb.sh`: one-shot local Debian package build.
- `howdy/src/pam/`: C++ PAM module.
- `howdy-gtk/src/`: GTK helper UI.
- `dist/` and `build/`: generated local build/package output.

## Build And Verify

Preferred quick checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile howdy/src/recorders/video_capture.py howdy/src/compare.py howdy/src/cli/test.py howdy-gtk/src/tab_video.py
meson compile -C build
```

For package validation, build a `.deb` using the repo script, then run:

```bash
./scripts/build-deb.sh
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
  The default config should use `device_path = auto`; `none` is legacy only.
- GTK preview should remain simple GLib/GTK code; do not add asyncio unless the
  event-loop integration is explicit and tested.
- Do not commit generated build output from `build/` or `dist/`.
- Keep hardware-free behavior covered in `tests/`; mock camera/OpenCV I/O rather
  than requiring `/dev/video*` in CI.

## Testing And Security Follow-Up

This is PAM/security-sensitive code. Prefer adding focused tests before broad
refactors:

- unit-test backend model matching, threshold handling, and model compatibility;
- unit-test camera candidate scoring and cache fallback behavior without real
  hardware;
- smoke-test package maintainer scripts and installed file permissions;
- add static checks for shell scripts and Python where practical;
- review PAM timeout paths, subprocess spawning, writable paths, log/cache file
  permissions, and config parsing as security-sensitive surfaces.

## Packaging Notes

The local package intentionally conflicts/replaces `howdy-gtk` and provides a
single `howdy` package containing the CLI, PAM module, GTK helper, config, and
OpenCV models.

When changing installed paths, update:

- `meson.options`
- generated path configuration under `howdy/src` and `howdy-gtk/src`
- `VERSION`
- `scripts/build-deb.sh`
- README package build instructions
