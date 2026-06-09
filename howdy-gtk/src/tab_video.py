import configparser

from i18n import _
import paths_factory

from gi.repository import Gtk as gtk
from gi.repository import Gdk as gdk
from gi.repository import GdkPixbuf as pixbuf
from gi.repository import GObject as gobject

MAX_HEIGHT = 300
MAX_WIDTH = 300


def on_page_switch(self, notebook, page, page_num):
    if page_num == 1:
        try:
            self.config = configparser.ConfigParser()
            self.config.read(paths_factory.config_file_path())
        except (OSError, configparser.Error):
            print(_("Can't open camera"))
            return

        path = self.config.get("video", "device_path", fallback="none")

        try:
            import cv2

            self.cv2 = cv2
        except ImportError:
            print(_("Can't import OpenCV2"))
            return

        self.capture = cv2.VideoCapture(path)
        if not self.capture.isOpened():
            print(_("Can't open camera"))
            self.capture.release()
            self.capture = None
            return

        opencvbox = self.builder.get_object("opencvbox")
        opencvbox.modify_bg(gtk.StateType.NORMAL, gdk.Color(red=0, green=0, blue=0))

        height = self.capture.get(self.cv2.CAP_PROP_FRAME_HEIGHT) or 1
        width = self.capture.get(self.cv2.CAP_PROP_FRAME_WIDTH) or 1

        self.scaling_factor = (MAX_HEIGHT / height) or 1

        if width * self.scaling_factor > MAX_WIDTH:
            self.scaling_factor = (MAX_WIDTH / width) or 1

        config_height = self.config.getfloat("video", "max_height", fallback=320.0)
        config_scaling = (config_height / height) or 1

        self.builder.get_object("videoid").set_text(path.split("/")[-1])
        self.builder.get_object("videores").set_text(
            str(int(width)) + "x" + str(int(height))
        )
        self.builder.get_object("videoresused").set_text(
            str(int(width * config_scaling)) + "x" + str(int(height * config_scaling))
        )
        self.builder.get_object("videorecorder").set_text(
            self.config.get("video", "recording_plugin", fallback=_("Unknown"))
        )

        gobject.timeout_add(20, self.capture_frame)

    elif self.capture is not None:
        self.capture.release()
        self.capture = None


def capture_frame(self):
    if self.capture is None:
        return False

    ret, frame = self.capture.read()
    if not ret or frame is None:
        return True

    frame = self.cv2.resize(
        frame,
        None,
        fx=self.scaling_factor,
        fy=self.scaling_factor,
        interpolation=self.cv2.INTER_AREA,
    )

    retval, buffer = self.cv2.imencode(".png", frame)
    if not retval:
        return True

    loader = pixbuf.PixbufLoader()
    loader.write(buffer)
    loader.close()
    buffer = loader.get_pixbuf()

    self.opencvimage.set_from_pixbuf(buffer)

    return True
