# Shows a small authentication status window.
import gi
import os
import select
import signal
import sys

import paths_factory
from i18n import _

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Gdk as gdk
from gi.repository import GdkPixbuf as gdkpixbuf
from gi.repository import GObject as gobject
from gi.repository import Gtk as gtk


class AuthWindow(gtk.Window):
	def __init__(self):
		gtk.Window.__init__(self, title=_("Howdy Authentication"))

		self.confirmation = False
		self.message_label = gtk.Label(label=_("Loading..."))
		self.subtext_label = gtk.Label(label="")
		self.button_box = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=8)
		self.allow_button = None
		self.deny_button = None

		self.set_resizable(False)
		self.set_keep_above(True)
		self.set_modal(True)
		self.set_accept_focus(True)
		self.set_focus_on_map(True)
		self.set_position(gtk.WindowPosition.CENTER)
		self.set_type_hint(gdk.WindowTypeHint.DIALOG)
		self.connect("destroy", self.exit)
		self.connect("delete_event", self.exit)
		self.connect("key-press-event", self.on_key_press)

		self.build_content()
		self.show_all()
		self.button_box.hide()

		gobject.timeout_add(100, self.catch_stdin)
		gtk.main()

	def build_content(self):
		root = gtk.Box(orientation=gtk.Orientation.HORIZONTAL, spacing=16)
		root.set_border_width(16)
		self.add(root)

		logo = self.build_logo()
		root.pack_start(logo, False, False, 0)

		text_box = gtk.Box(orientation=gtk.Orientation.VERTICAL, spacing=8)
		root.pack_start(text_box, True, True, 0)

		self.message_label.set_xalign(0)
		self.message_label.set_line_wrap(True)
		self.message_label.get_style_context().add_class("title")
		text_box.pack_start(self.message_label, False, False, 0)

		self.subtext_label.set_xalign(0)
		self.subtext_label.set_line_wrap(True)
		text_box.pack_start(self.subtext_label, False, False, 0)

		self.deny_button = gtk.Button(label=_("Deny"))
		self.deny_button.connect("clicked", self.deny)
		self.button_box.pack_start(self.deny_button, True, True, 0)

		self.allow_button = gtk.Button(label=_("Allow"))
		self.allow_button.set_can_default(True)
		self.allow_button.get_style_context().add_class("suggested-action")
		self.allow_button.connect("clicked", self.allow)
		self.button_box.pack_start(self.allow_button, True, True, 0)
		text_box.pack_start(self.button_box, False, False, 0)

	def build_logo(self):
		logo_path = paths_factory.logo_path()
		if os.path.exists(logo_path):
			pixbuf = gdkpixbuf.Pixbuf.new_from_file_at_scale(logo_path, 64, 64, True)
			return gtk.Image.new_from_pixbuf(pixbuf)

		image = gtk.Image.new_from_icon_name("dialog-password", gtk.IconSize.DIALOG)
		image.set_pixel_size(64)
		return image

	def update_message(self, message):
		self.message_label.set_text(message)

	def update_subtext(self, subtext):
		self.subtext_label.set_text(subtext)
		self.subtext_label.set_visible(bool(subtext))

	def set_confirmation(self, enabled):
		self.confirmation = enabled
		self.button_box.set_visible(enabled)
		if enabled:
			self.present()
			self.set_default(self.allow_button)
			self.allow_button.grab_focus()
			gobject.idle_add(self.focus_confirmation)

	def focus_confirmation(self):
		self.present_with_time(gdk.CURRENT_TIME)
		if self.get_window() is not None:
			self.get_window().focus(gdk.CURRENT_TIME)
		self.allow_button.grab_focus()
		return False

	def catch_stdin(self):
		while True:
			ready, _writable, _errors = select.select([sys.stdin], [], [], 0)
			if not ready:
				return True

			comm = sys.stdin.readline()
			if comm == "":
				gtk.main_quit()
				return False

			self.handle_command(comm.rstrip("\n"))

	def handle_command(self, comm):
		if len(comm) < 2 or comm[1] != "=":
			return

		command = comm[0]
		value = comm[2:].strip()

		if command == "M":
			self.update_message(value)
		elif command == "S":
			self.update_subtext(value)
		elif command == "C":
			self.set_confirmation(value == "1")

	def on_key_press(self, _widget, event):
		if not self.confirmation:
			return False

		if event.keyval in (gdk.KEY_Return, gdk.KEY_KP_Enter, gdk.KEY_ISO_Enter, gdk.KEY_space):
			focus = self.get_focus()
			if focus == self.deny_button:
				self.deny()
			else:
				self.allow()
			return True

		if event.keyval == gdk.KEY_Escape:
			self.deny()
			return True

		return False

	def allow(self, _widget=None):
		print("ALLOW", flush=True)
		self.exit()

	def deny(self, _widget=None):
		print("DENY", flush=True)
		self.exit()

	def exit(self, _widget=None, _context=None):
		gtk.main_quit()
		return True


def gtk_display_available():
	"""Return whether GTK can create windows in the current environment."""
	initialized, _argv = gtk.init_check(sys.argv)
	return initialized


signal.signal(signal.SIGINT, signal.SIG_DFL)

# The auth popup is optional. PAM can invoke it from environments without a
# usable GUI session; exiting cleanly avoids Apport crash reports.
if not gtk_display_available():
	sys.exit(0)

window = AuthWindow()
