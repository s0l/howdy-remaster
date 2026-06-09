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
set -euo pipefail

VERSION="${VERSION:-3.0.0+opencv-local}"
ARCH="${ARCH:-amd64}"
BUILD_DIR="dist/howdy-deb-build"
ROOT_DIR="dist/howdy-deb-root"
DEB_PATH="dist/howdy-opencv-sface_${VERSION}_${ARCH}.deb"

rm -rf "$BUILD_DIR" "$ROOT_DIR" "$DEB_PATH"

meson setup "$BUILD_DIR" \
  --prefix=/usr \
  --buildtype=release \
  -Dconfig_dir=/etc/howdy \
  -Ddlib_data_dir=/etc/howdy/dlib-data \
  -Dface_data_dir=/etc/howdy/face-models \
  -Duser_models_dir=/etc/howdy/models \
  -Dpy_sources_dir=/lib/security \
  -Dpam_dir=/lib/security \
  -Dinstall_pam_config=true

meson compile -C "$BUILD_DIR"
DESTDIR="$PWD/$ROOT_DIR" meson install -C "$BUILD_DIR" --no-rebuild

mkdir -p \
  "$ROOT_DIR/DEBIAN" \
  "$ROOT_DIR/etc/howdy/models" \
  "$ROOT_DIR/var/cache/howdy" \
  "$ROOT_DIR/var/log/howdy/snapshots"

install -m 0644 howdy/src/config.ini "$ROOT_DIR/etc/howdy/config.ini"

cat > "$ROOT_DIR/DEBIAN/control" <<EOF
Package: howdy
Version: $VERSION
Section: misc
Priority: optional
Architecture: $ARCH
Maintainer: local <root@localhost>
Installed-Size: 39000
Depends: libc6, libgcc-s1, libstdc++6, libpam0g, libevdev2, libinih1, python3, python3-numpy, python3-opencv, python3-gi, gir1.2-gtk-3.0, curl | wget
Recommends: v4l-utils
Conflicts: howdy-gtk
Replaces: howdy-gtk
Provides: howdy
Description: Windows Hello style authentication for Linux, OpenCV SFace build
 Howdy uses a camera and local face recognition to authenticate users.
 This build uses OpenCV YuNet and SFace ONNX models instead of dlib.
EOF

cat > "$ROOT_DIR/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

mkdir -p /etc/howdy/models /var/cache/howdy /var/log/howdy /var/log/howdy/snapshots

if [ -f /usr/local/bin/howdy ] && grep -q "/usr/local/lib/.*/howdy/cli.py" /usr/local/bin/howdy 2>/dev/null; then
	rm -f /usr/local/bin/howdy
fi

chown -R root:root /lib/security/howdy /lib/security/howdy-gtk /etc/howdy /var/cache/howdy /var/log/howdy
chown root:root /usr/bin/howdy /usr/bin/howdy-gtk /lib/security/pam_howdy.so

chmod 755 /lib/security/howdy /lib/security/howdy-gtk /etc/howdy /etc/howdy/face-models /var/log/howdy /var/log/howdy/snapshots
chmod 700 /etc/howdy/models /var/cache/howdy
chmod 755 /usr/bin/howdy /usr/bin/howdy-gtk /lib/security/pam_howdy.so

if command -v pam-auth-update >/dev/null 2>&1; then
	pam-auth-update --package || true
fi

exit 0
EOF

cat > "$ROOT_DIR/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
	if command -v pam-auth-update >/dev/null 2>&1; then
		pam-auth-update --package || true
	fi
fi

exit 0
EOF

chmod 755 "$ROOT_DIR/DEBIAN/postinst" "$ROOT_DIR/DEBIAN/prerm"
dpkg-deb --build --root-owner-group "$ROOT_DIR" "$DEB_PATH"

echo "Built $DEB_PATH"
```

To use a different package version, set `VERSION` before running the block:

```bash
VERSION=3.0.0+opencv6
```

There is no separate dlib build step. The OpenCV YuNet/SFace ONNX files are
installed from `howdy/src/face-models`.

## Install The Package

```bash
sudo apt install ./dist/howdy-opencv-sface_3.0.0+opencv-local_amd64.deb
hash -r
```

If you built with a different `VERSION`, use the matching filename.

The package installs the PAM config through `pam-auth-update --package`.

## Configure Camera

The default config uses:

```ini
device_path = none
```

`none` and `auto` both enable automatic camera selection. The resolver scores
available V4L devices and prefers likely IR cameras:

- names containing `infrared` or `ir`
- names containing `depth`
- camera/webcam names
- stable `/dev/v4l/by-path` or `/dev/v4l/by-id` paths
- grayscale frames when probing succeeds

After the first successful auto-detection, Howdy caches the selected device in:

```text
/var/cache/howdy/device_path
```

Normal PAM authentication uses the cached camera directly. A full device scan is
only retried when the cached device is missing or cannot be opened.

To force a manual camera path:

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
