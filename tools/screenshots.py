"""Render Lime's real window with made-up demo data, for store screenshots.

Usage, from the project root:  PYTHONPATH=. python3 tools/screenshots.py screenshots
"""
import os
import sys
import tempfile
import time

demo = tempfile.mkdtemp(prefix="lime-demo-")
for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
    os.environ[var] = os.path.join(demo, var.lower())  # keep the real history out of it

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from phonemessages import app as A  # noqa: E402
from phonemessages.store import Store, conv_key  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
os.makedirs(A.DATA_DIR, exist_ok=True)
store = Store(os.path.join(A.DATA_DIR, "messages.db"))

# fictional people; 555-01xx numbers are reserved for fiction
people = {
    "+15555550101": "Maya Chen",
    "+15555550102": "Sam Rivera",
    "+15555550103": "Jordan Lee",
    "+15555550104": "Priya Patel",
    "+15555550105": "Alex Morgan",
    "+15555550106": "Dad",
    "+15555550107": "Chris Walker",
    "+15555550108": "Emma Johnson",
}
store.replace_contacts({conv_key(a): (n, None, a) for a, n in people.items()})

now = time.time()
day = time.mktime(time.localtime(now)[:3] + (18, 40, 0, 0, 0, -1))  # today, 6:40 pm


def add(addr, text, out, minutes, read=True):
    msg_id = store.add(addr, text, out, ts=day + minutes * 60, handle=None if out else "h%d" % add.n)
    add.n += 1
    if read:
        store.mark_read(conv_key(addr))
    return msg_id


add.n = 0
add("+15555550105", "Can you send me the notes from today?", False, -60 * 26)
add("+15555550105", "Sure, emailing them now", True, -60 * 26 + 3)
add("+15555550106", "Call me when you're free", False, -60 * 5)
add("+15555550104", "Thanks for helping with the move!", False, -180)
add("+15555550104", "Anytime 😊", True, -176)
add("+15555550103", "Attachment: 1 Image", False, -95)
add("+15555550102", "Running 10 min late, sorry!", False, -12, read=False)

maya = "+15555550101"
add(maya, "Are we still on for the hike tomorrow?", False, -21)
add(maya, "Yes! Trailhead at 8?", True, -19)
add(maya, "Perfect. I found the view we talked about", False, -18)
add(maya, "Attachment: 1 Image", False, -18)
add(maya, 'Loved “Attachment: 1 Image”', True, -17)
add(maya, "That looks amazing 🤩", True, -17)
add(maya, "Should I bring snacks?", False, -2)
add(maya, "Definitely. I'll bring coffee ☕", True, -1)

Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
screen = Gdk.Screen.get_default()
for css, priority in ((A.CSS, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION),
                      (A.bubble_css({}), Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1),
                      (A.TITLEBUTTON_CSS, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)):
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(screen, provider, priority)


class FakeClient(GObject.Object):
    __gsignals__ = {"state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str))}
    state = "connected"


A.paired_devices = lambda: [("00:00:00:00:00:01", "iPhone")]
app = Gtk.Application(application_id="io.github.ThatSwimmerGuy.LimeScreenshots")
app.store = store
app.client = FakeClient()
shots = []
hide = []  # widgets the real window keeps hidden, which show_all() would reveal


def capture(widget, name, width, height):
    """Move the window's titlebar and contents into an offscreen window and save a PNG."""
    off = Gtk.OffscreenWindow()
    widget.set_size_request(width, height)
    off.add(widget)
    off.show_all()
    for hidden in hide:
        hidden.hide()
    shots.append((off, name))


def activate(application):
    win = A.Window(application)
    for row in win.conv_list.get_children():
        if row.display == "Maya Chen":
            win.conv_list.select_row(row)
    win.entry.set_text("")
    hide.extend([win.infobar, win.reply_bar])
    header, body = win.get_titlebar(), win.get_child()
    win.remove(body)
    win.set_titlebar(None)
    frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    frame.pack_start(header, False, False, 0)
    frame.pack_start(body, True, True, 0)
    capture(frame, "conversation.png", 1000, 680)
    GLib.timeout_add(1200, save)


def save():
    for off, name in shots:
        off.get_pixbuf().savev(os.path.join(out, name), "png", [], [])
        print("saved", name)
    app.quit()
    return False


app.connect("activate", activate)
app.run([])
