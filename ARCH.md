# Architecture Notes

This fork is PAM/security-sensitive. Changes to authentication flow should be
reviewed as privilege-boundary changes, not as ordinary UI or camera changes.

## Polkit Confirmation Flow

Face recognition is convenient for terminal PAM services such as `sudo`, but it
has a different threat model when used through graphical privilege prompts. A
program can trigger a polkit request while the user's face is already in front of
the laptop camera. If face recognition alone is enough to satisfy the PAM stack,
the privilege escalation can be approved without an intentional user action.

The default config therefore lists `polkit-1`, `sudo`, and `sudo-i` in
`confirmation_services`. The PAM module passes `HOWDY_CONFIRM_AUTH=1` to the
compare process for those services. After a successful face match, `compare.py`
asks the GTK auth UI for an explicit `ALLOW` response. `DENY`, a closed UI, an
unavailable display, unreadable stdout, or a timeout must be treated as
authentication failure. This failure should let the surrounding PAM stack fall
back to its normal password path rather than silently granting access.

Keep this flow narrow:

- apply it to services where ambient face presence is dangerous;
- keep the stdout protocol small and exact (`ALLOW` or `DENY`);
- never treat face recognition alone as approval for graphical privilege
  escalation;
- prefer failing closed when the confirmation UI cannot be shown.

## GTK Auth UI Corner Cases

The historical `authsticky.py` UI used a transparent, undecorated, always-on-top
Cairo-drawn notification window. That is acceptable for a passive "identifying
you" notice, but it is the wrong primitive for a security confirmation dialog.
Do not put interactive confirmation buttons on a manually painted transparent
notification surface.

The problematic shape is:

- `set_app_paintable(True)`;
- `Gdk.Screen.get_rgba_visual()` plus `set_visual()`;
- `GDK_WINDOW_TYPE_HINT_NOTIFICATION`;
- `set_decorated(False)`;
- manual Cairo button drawing and coordinate hit testing.

On KDE Wayland this class of window is especially fragile. During development on
Ubuntu 26.04 / KDE Wayland, KWin was already emitting OpenGL messages such as:

```text
kwin_scene_opengl: 0x500: GL_INVALID_ENUM error generated. Invalid <face>.
kwin_scene_opengl: Invalid framebuffer status: "GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT"
```

Those messages started at session startup, before the local Howdy package was
installed, so they were not proof that Howdy broke KWin. However, a transparent
RGBA notification window is exactly the kind of compositor-sensitive surface that
can amplify or trigger weird behavior in an already unstable KWin/driver state.
For the auth confirmation path, avoid that corner case completely.

The confirmation UI should be an ordinary opaque GTK toplevel/dialog using real
GTK widgets:

- no alpha visual;
- no app-paintable background;
- no notification type hint;
- no hand-drawn interactive controls;
- normal `Gtk.Button` click handling;
- non-blocking stdin polling so the GTK event loop remains responsive.

## Validation Checklist

For changes touching PAM, compare, or auth UI:

```bash
python3 -m py_compile howdy/src/recorders/video_capture.py howdy/src/compare.py howdy/src/cli/test.py howdy-gtk/src/tab_video.py howdy-gtk/src/authsticky.py
python3 -m unittest discover -s tests -v
meson compile -C build
./scripts/build-deb.sh
apt install --simulate ./dist/howdy-opencv-sface_<version>_amd64.deb
```

Manual validation still needs real hardware and a real desktop session:

```bash
sudo howdy test
sudo su -
```

For the polkit path, trigger a real graphical privilege prompt and verify that:

- face recognition opens the confirmation UI;
- `Deny` does not approve the polkit request;
- closing the UI does not approve the polkit request;
- timeout does not approve the polkit request;
- blocked camera reads do not hang PAM indefinitely;
- the camera is released before waiting for interactive confirmation;
- `Allow` approves only after a successful face match;
- `Enter` and `Space` activate `Allow` when the confirmation window has focus;
- `Enter` and `Space` activate `Deny` if keyboard focus was moved to `Deny`;
- `Esc` activates `Deny`;
- KWin/desktop logs do not get new spam bursts specifically correlated with the
  Howdy confirmation window.
