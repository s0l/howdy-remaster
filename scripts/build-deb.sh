#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

version_file="$repo_root/VERSION"
version="${VERSION:-$(tr -d '[:space:]' < "$version_file")}"
arch="${ARCH:-amd64}"
build_dir="${BUILD_DIR:-dist/howdy-deb-build}"
root_dir="${ROOT_DIR:-dist/howdy-deb-root}"
deb_path="${DEB_PATH:-dist/howdy-opencv-sface_${version}_${arch}.deb}"

rm -rf "$build_dir" "$root_dir" "$deb_path"

meson setup "$build_dir" \
	--prefix=/usr \
	--buildtype=release \
	-Dconfig_dir=/etc/howdy \
	-Ddlib_data_dir=/etc/howdy/dlib-data \
	-Dface_data_dir=/etc/howdy/face-models \
	-Duser_models_dir=/etc/howdy/models \
	-Dpy_sources_dir=/lib/security \
	-Dpam_dir=/lib/security \
	-Dinstall_pam_config=true

meson compile -C "$build_dir"
DESTDIR="$repo_root/$root_dir" meson install -C "$build_dir" --no-rebuild

mkdir -p \
	"$root_dir/DEBIAN" \
	"$root_dir/etc/howdy/models" \
	"$root_dir/var/cache/howdy" \
	"$root_dir/var/log/howdy/snapshots"

install -m 0644 howdy/src/config.ini "$root_dir/etc/howdy/config.ini"
chmod 755 "$root_dir/var" "$root_dir/var/cache" "$root_dir/var/log" "$root_dir/etc/howdy"
chmod 700 "$root_dir/etc/howdy/models" "$root_dir/var/cache/howdy" "$root_dir/var/log/howdy" "$root_dir/var/log/howdy/snapshots"

cat > "$root_dir/DEBIAN/control" <<EOF
Package: howdy
Version: $version
Section: misc
Priority: optional
Architecture: $arch
Maintainer: local <root@localhost>
Installed-Size: 39000
Depends: libc6, libgcc-s1, libstdc++6, libpam0g, libevdev2, libinih1, python3, python3-numpy, python3-opencv, python3-gi, gir1.2-gtk-3.0, acl, curl | wget
Recommends: v4l-utils
Conflicts: howdy-gtk
Replaces: howdy-gtk
Provides: howdy
Description: Windows Hello style authentication for Linux, OpenCV SFace build
 Howdy uses a camera and local face recognition to authenticate users.
 This build uses OpenCV YuNet and SFace ONNX models instead of dlib.
EOF

cat > "$root_dir/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

mkdir -p /etc/howdy/models /var/cache/howdy /var/log/howdy /var/log/howdy/snapshots

if [ -f /usr/local/bin/howdy ] && grep -q "/usr/local/lib/.*/howdy/cli.py" /usr/local/bin/howdy 2>/dev/null; then
	rm -f /usr/local/bin/howdy
fi

find /lib/security/howdy /lib/security/howdy-gtk -xdev -exec chown -h root:root {} +
chown root:root /etc/howdy /etc/howdy/models /etc/howdy/face-models /var/cache/howdy /var/log/howdy /var/log/howdy/snapshots
chown root:root /usr/bin/howdy /usr/bin/howdy-gtk /lib/security/pam_howdy.so

chmod 755 /lib/security/howdy /lib/security/howdy-gtk /etc/howdy /etc/howdy/face-models
find /lib/security/howdy /lib/security/howdy-gtk -xdev -type d -exec chmod 755 {} +
find /lib/security/howdy /lib/security/howdy-gtk -xdev -type f -exec chmod 644 {} +
chmod 700 /etc/howdy/models /var/cache/howdy
chmod 700 /var/log/howdy /var/log/howdy/snapshots
chmod 644 /etc/howdy/config.ini
chmod 755 /usr/bin/howdy /usr/bin/howdy-gtk /lib/security/pam_howdy.so

if command -v setfacl >/dev/null 2>&1; then
	for model_file in /etc/howdy/models/*.dat; do
		[ -e "$model_file" ] || continue
		user="${model_file##*/}"
		user="${user%.dat}"
		uid="$(id -u -- "$user" 2>/dev/null || true)"
		if [ -n "$uid" ]; then
			setfacl -m "u:$uid:--x" /etc/howdy/models || true
			setfacl -m "u:$uid:r--" "$model_file" || true
		fi
	done
fi

if command -v pam-auth-update >/dev/null 2>&1; then
	pam-auth-update --package || true
fi

exit 0
EOF

cat > "$root_dir/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "deconfigure" ]; then
	if command -v pam-auth-update >/dev/null 2>&1; then
		pam-auth-update --package || true
	fi
fi

exit 0
EOF

chmod 755 "$root_dir/DEBIAN/postinst" "$root_dir/DEBIAN/prerm"
dpkg-deb --build --root-owner-group "$root_dir" "$deb_path"

echo "$deb_path"
