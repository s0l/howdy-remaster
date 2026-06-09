# Howdy Remaster

Howdy Remaster is a modernized Howdy build for Linux PAM authentication.
It keeps the familiar `howdy` CLI and PAM flow, but uses OpenCV YuNet/SFace
models at runtime instead of dlib.

This fork is currently focused on Ubuntu/Debian-style systems where Howdy is
installed as a normal `.deb` package:

- PAM module: `/lib/security/pam_howdy.so`
- Python sources: `/lib/security/howdy`
- GTK helper: `/lib/security/howdy-gtk`
- Config: `/etc/howdy/config.ini`
- Face models: `/etc/howdy/models`
- OpenCV ONNX models: `/etc/howdy/face-models`
- Logs: `/var/log/howdy`
- Auto-detected camera cache: `/var/cache/howdy/device_path`

Do not use Howdy as the only authentication method on a system. Keep password
authentication available.

## Install Build Dependencies

On Ubuntu:

```bash
sudo apt update
sudo apt install -y \
  build-essential \
  meson \
  ninja-build \
  pkg-config \
  dpkg-dev \
  libpam0g-dev \
  libevdev-dev \
  libinih-dev \
  libopencv-dev \
  libopencv-contrib-dev \
  python3 \
  python3-gi \
  python3-numpy \
  python3-opencv \
  gir1.2-gtk-3.0 \
  v4l-utils \
  curl
```

If your Ubuntu release provides a versioned OpenCV contrib runtime package
such as `libopencv-contrib410`, install it too. `apt` will normally pull the
right runtime libraries through `python3-opencv` and `libopencv-contrib-dev`.

Optional tools:

```bash
sudo apt install -y gh ccache
```

`gh` is the GitHub CLI. Use it with:

```bash
gh auth login
```

## One-Shot Debian Package Build

Run this from the repository root:

```bash
./scripts/build-deb.sh
```

The package version is stored in `VERSION`. To override it for a local build:

```bash
VERSION=3.0.0+local ./scripts/build-deb.sh
```

There is no separate dlib build step. The OpenCV YuNet/SFace ONNX files are
installed from `howdy/src/face-models`.

## Install The Package

```bash
sudo apt install ./dist/howdy-opencv-sface_$(cat VERSION)_amd64.deb
hash -r
```

If you built with a different `VERSION`, use the matching filename.

The package installs the PAM config through `pam-auth-update --package`.

## Camera Selection

No camera configuration is normally needed. The default config uses:

```ini
device_path = auto
```

`auto` means: find a suitable camera automatically. Howdy scans available V4L
devices, scores them, and prefers likely IR cameras:

- names containing `infrared` or `ir`
- names containing `depth`
- camera/webcam names
- stable `/dev/v4l/by-path` or `/dev/v4l/by-id` paths
- grayscale frames when probing succeeds

After the first successful auto-detection, Howdy caches the selected device in:

```text
/var/cache/howdy/device_path
```

Normal PAM authentication uses the cached camera directly. It does not rescan all
video devices unless the cached camera is missing or cannot be opened.

`none` is still accepted as a legacy synonym for `auto`, but new configs should
use `auto`.

Manual configuration is only an escape hatch if auto-detection chooses the wrong
device:

```bash
sudo howdy config
```

Set, for example:

```ini
device_path = /dev/v4l/by-path/pci-0000:07:00.0-usb-0:1:1.2-video-index0
```

## Add And Test Face Models

Add a model for the current user:

```bash
sudo howdy add
```

Open the camera test UI:

```bash
sudo howdy test
```

The test command prints recognition status to the terminal:

- `NO FACE`
- `NO MATCH: score=... threshold=...`
- `MATCH: <label> score=... threshold=...`

Try PAM authentication in a new terminal:

```bash
sudo su -
```

Successful authentication prints a sudo/PAM message such as:

```text
[sudo] Identified face as s0l
```

Runtime logs are written to:

```text
/var/log/howdy/compare.log
```

## KDE/SDDM Login

SDDM starts PAM authentication only after a login request is submitted. On the
KDE login screen, select the user, leave the password field empty, and press
Enter or the login button to let Howdy authenticate the face.

The transient `howdy-gtk` auth window is best-effort feedback for desktop PAM
prompts such as `sudo`. On the SDDM greeter and Plasma lock screen it may not be
shown because those processes run in a restricted display-manager environment.
Password authentication should remain available as the fallback path.

Plasma's lock screen uses KScreenLocker and the PAM service `kde`. Unlike `sudo`,
the lock-screen greeter authenticates as the locked user, so the package grants
that user read-only ACL access to their own `/etc/howdy/models/<user>.dat` file
and traverse-only ACL access to `/etc/howdy/models`. It does not make the model
directory world-readable.

If the display manager shows PAM informational messages, enabling
`detection_notice` in `/etc/howdy/config.ini` may display a short facial
authentication notice. Some SDDM themes ignore those messages and only show
generic login success or failure states.

## CLI

```text
howdy [-U user] [-y] command [argument]
```

Common commands:

| Command   | Description                                 |
|-----------|---------------------------------------------|
| `add`     | Add a face model                            |
| `clear`   | Remove all face models                      |
| `config`  | Open `/etc/howdy/config.ini`                |
| `disable` | Disable or enable Howdy                     |
| `list`    | List saved face models                      |
| `remove`  | Remove a specific model                     |
| `snapshot`| Take a camera snapshot                      |
| `test`    | Test camera capture and recognition         |

## Development Build

For a quick local compile without creating a `.deb`:

```bash
meson setup build
meson compile -C build
```

This only verifies the build. For system installation, prefer the `.deb` flow
above so file ownership, PAM config, cache directories, and package upgrades are
handled consistently.

## Security Notes

Howdy is convenience authentication, not a password replacement. Face
recognition can be fooled by similar-looking people or presentation attacks.

Keep these rules:

- keep password authentication enabled;
- do not use Howdy as the sole authentication method;
- keep installed files root-owned and read-only for regular users;
- prefer `/lib/security` for the PAM module and Python runtime files.
