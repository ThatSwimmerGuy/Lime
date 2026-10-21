"""Lime (Linux iPhone Messaging Engine): read and send iPhone messages from Linux over Bluetooth."""
import hashlib
import json
import os
import re
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import Gio, GLib, Gtk, Gdk, Notify, Pango  # noqa: E402

from . import reactions  # noqa: E402
from .contacts import ContactSync  # noqa: E402
from .map_client import MapClient, paired_devices  # noqa: E402
from .store import Store, conv_key  # noqa: E402

APP_ID = "io.github.ThatSwimmerGuy.Lime"
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "phone-messages")
CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "phone-messages")
AVATAR_DIR = os.path.join(DATA_DIR, "avatars")
CONFIG_PATH = os.path.join(GLib.get_user_config_dir(), "phone-messages", "config.json")
RECONNECT_SECONDS = 20
GROUP_GAP = 60          # seconds between messages that still count as one group
TIMESTAMP_GAP = 15 * 60  # show a centred timestamp when messages are this far apart

# iOS dark mode palette
CSS = b"""
/* one flat grey behind everything; change it here to make the app lighter or darker */
@define-color app_bg #161618;
@define-color raised_bg #242427;
window, .chat-bg, .chat-bg viewport, .sidebar, .sidebar viewport, list {
    background-color: @app_bg; color: #ffffff;
}
/* top bar, modelled on the macOS toolbar */
headerbar {
    background-image: none; background-color: @app_bg; border: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06); box-shadow: none;
    color: #ffffff; min-height: 50px; padding: 0 10px;
}
.csd headerbar, headerbar.titlebar { border-radius: 10px 10px 0 0; }
headerbar:backdrop { background-color: @app_bg; }
headerbar .title { font-weight: 700; font-size: 13px; }
headerbar .subtitle { font-size: 11px; color: #8e8e93; }
headerbar button:not(.titlebutton) {
    background-image: none; background-color: transparent; border: none; box-shadow: none;
    border-radius: 6px; color: #bcbcc0; min-height: 28px; min-width: 32px; padding: 0 6px;
}
headerbar button:not(.titlebutton):hover { background-color: rgba(255, 255, 255, 0.09); color: #ffffff; }
headerbar button:not(.titlebutton):active,
headerbar button:not(.titlebutton):checked { background-color: rgba(255, 255, 255, 0.16); }
headerbar:backdrop button:not(.titlebutton) { color: #6e6e73; }
/* device picker and Connect as rounded capsules */
headerbar combobox button:not(.titlebutton), headerbar button.capsule:not(.titlebutton) {
    background-color: @raised_bg; color: #ffffff; border-radius: 7px; min-height: 26px;
    padding: 0 12px; font-size: 13px; font-weight: 500;
    box-shadow: inset 0 1px rgba(255, 255, 255, 0.08);
}
headerbar combobox button:not(.titlebutton):hover,
headerbar button.capsule:not(.titlebutton):hover { background-color: #303034; }
headerbar button.capsule.suggested:not(.titlebutton) { background-color: #0a84ff; }
headerbar button.capsule.suggested:not(.titlebutton):hover { background-color: #2a95ff; }
/* 1px hairline; the theme pads the separator for an easier grab, so only draw the line itself */
paned > separator { background-color: transparent; background-image: image(rgba(255, 255, 255, 0.06));
                    background-size: 1px 1px; }

/* sidebar */
.big-title { font-size: 26px; font-weight: 800; margin: 14px 16px 6px 16px; }
.search {
    background-color: @raised_bg; border: none; border-radius: 10px; box-shadow: none;
    color: #ffffff; min-height: 34px; margin: 4px 12px 10px 12px;
}
.search image { color: #8e8e93; }
list row { padding: 0; margin: 0 8px; border-radius: 12px; background-color: transparent; }
list row:selected { background-color: #2c2c2e; }
list row:hover:not(:selected) { background-color: #1e1e21; }
.conv-name { font-weight: 600; font-size: 15px; color: #ffffff; }
.conv-time, .conv-preview { color: #8e8e93; font-size: 13px; }
.settings-title { font-size: 17px; font-weight: 700; }
.settings-section { color: #8e8e93; font-size: 13px; font-weight: 600; margin-top: 4px; }
.contact-letter { color: #8e8e93; font-size: 13px; font-weight: 700; margin: 10px 18px 2px 18px; }
.row-sep { background-color: #38383a; min-height: 1px; margin-left: 72px; }

/* avatars: grey gradient circle with initials, like iOS contacts without a photo */
.avatar {
    border-radius: 999px; color: #ffffff; font-weight: 600;
    background-image: linear-gradient(to bottom, #a5abb8, #858994);
}
.avatar.small { min-width: 44px; min-height: 44px; font-size: 17px; }
.avatar.large { min-width: 52px; min-height: 52px; font-size: 21px; }

/* chat header */
.chat-header { background-color: @app_bg; border-bottom: 1px solid rgba(255, 255, 255, 0.06); padding: 8px 0 6px 0; }
.chat-header-name { font-size: 12px; color: #ffffff; }
.chat-header-address { font-size: 11px; color: #8e8e93; }

/* bubbles */
.bubble { border-radius: 18px; padding: 7px 13px; font-size: 15px; }
.bubble.in { background-color: #2c2c2e; color: #ffffff; }
.bubble.out { background-color: #0a84ff; color: #ffffff; }
.bubble.in.tail { border-bottom-left-radius: 5px; }
.bubble.out.tail { border-bottom-right-radius: 5px; }
.bubble.failed { background-color: rgba(10, 132, 255, 0.45); }
.bubble.attachment { padding: 9px 14px; }
.bubble selection { background-color: rgba(255, 255, 255, 0.35); }
.timestamp { color: #8e8e93; font-size: 11px; font-weight: 600; margin: 12px 0 6px 0; }
.receipt { color: #8e8e93; font-size: 11px; margin: 2px 4px 0 4px; }
.receipt.receipt-error { color: #ff453a; }
.empty-chat { color: #8e8e93; font-size: 15px; }

/* compose bar */
.compose { background-color: @app_bg; padding: 8px 12px 12px 12px; }
.pill { border: 1px solid #3a3a3c; border-radius: 20px; padding: 2px 3px 2px 12px; background-color: @app_bg; }
.pill entry {
    background-color: transparent; background-image: none; border: none; box-shadow: none;
    color: #ffffff; font-size: 15px; min-height: 30px;
}
.send-btn {
    border-radius: 999px; min-width: 28px; min-height: 28px; padding: 0;
    background-image: none; background-color: #0a84ff; border: none; box-shadow: none; color: #ffffff;
}
.send-btn:disabled { background-color: #3a3a3c; color: #8e8e93; }

/* unread */
.unread-dot { background-color: #0a84ff; border-radius: 999px; min-width: 10px; min-height: 10px; }
.unread-dot.read { background-color: transparent; }
.conv-preview.unread { color: #ffffff; }

/* reactions */
.reaction-badge { background-color: #3a3a3c; border: 2px solid @app_bg; border-radius: 999px;
                  padding: 1px 6px; font-size: 13px; }
.reaction-badge.mine { background-color: #0a84ff; }

/* replies */
.reply-bar { background-color: @raised_bg; border-left: 3px solid #0a84ff; border-radius: 8px;
             padding: 5px 6px 5px 10px; margin: 0 2px 8px 2px; }
.reply-bar-title { color: #0a84ff; font-size: 12px; font-weight: 600; }
.reply-bar-text { color: #8e8e93; font-size: 13px; }
.reply-bar button { background-image: none; background-color: transparent; border: none;
                    box-shadow: none; color: #8e8e93; padding: 2px; min-height: 0; min-width: 0; }
.reply-quote { color: #8e8e93; font-size: 13px; border: 1px solid #3a3a3c; border-radius: 14px;
               padding: 4px 11px; margin-bottom: 2px; }

infobar, infobar revealer > box { background-color: @raised_bg; background-image: none; border: none; color: #ffffff; }
infobar.warning revealer > box { border-left: 3px solid #ff9f0a; }
infobar.error revealer > box { border-left: 3px solid #ff453a; }
"""

# Traffic-light window buttons. KDE installs its own titlebutton images as user CSS,
# which outranks application CSS, so these load at a higher priority.
TITLEBUTTON_CSS = b"""
headerbar button.titlebutton {
    border: none; box-shadow: none; border-radius: 999px;
    min-width: 12px; min-height: 12px; padding: 0; margin: 0 4px 0 0;
    background-size: 0 0;  /* the theme draws its glyph as a background image; hide it */
}
headerbar button.titlebutton image { opacity: 0; }
headerbar button.titlebutton:hover { background-size: 10px 10px; color: rgba(0, 0, 0, 0.6); }
headerbar button.titlebutton.close { background-color: #ff5f57; }
headerbar button.titlebutton.minimize { background-color: #febc2e; }
headerbar button.titlebutton.maximize { background-color: #28c840; }
headerbar:backdrop button.titlebutton { background-color: #3a3a3c; }
headerbar button.titlebutton:active { opacity: 0.75; }
"""

SETUP_HELP = (
    "<b>Not connected to your iPhone.</b>\n"
    "1. Pair the iPhone with this laptop (see README).\n"
    "2. On the iPhone: Settings → Bluetooth → ⓘ next to this laptop → turn on <b>Show Notifications</b>.\n"
    "3. Choose the iPhone above and press Connect."
)

CONTACTS_HELP = (
    "<b>Showing numbers instead of names?</b> On the iPhone: Settings → Bluetooth → ⓘ next to "
    "this laptop → turn on <b>Sync Contacts</b>, then press Disconnect and Connect."
)


# Bubble colours the user can change; the defaults match the CSS above
BUBBLE_COLORS = [  # (config key, label, default)
    ("out_bg", "Sent bubble", "#0a84ff"),
    ("out_fg", "Sent text", "#ffffff"),
    ("in_bg", "Received bubble", "#2c2c2e"),
    ("in_fg", "Received text", "#ffffff"),
]


# Where the traffic-light window buttons sit; left is the Mac layout
WINDOW_BUTTON_LAYOUTS = {
    "left": "close,minimize,maximize:",
    "right": ":minimize,maximize,close",
}


def bubble_css(colors):
    c = {key: colors.get(key, default) for key, _, default in BUBBLE_COLORS}
    failed = Gdk.RGBA()
    failed.parse(c["out_bg"])
    failed.alpha = 0.45
    return (
        ".bubble.in { background-color: %s; color: %s; }\n"
        ".bubble.out { background-color: %s; color: %s; }\n"
        ".bubble.failed { background-color: %s; }\n"
        % (c["in_bg"], c["in_fg"], c["out_bg"], c["out_fg"], failed.to_string())
    ).encode()


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f)


def list_time(ts):
    """Conversation list style: 14:32 / Yesterday / Monday / 12/10/2026."""
    t = time.localtime(ts)
    days = (time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)) -
            time.mktime(t[:3] + (0, 0, 0, 0, 0, -1))) / 86400
    if days < 1:
        return time.strftime("%H:%M", t)
    if days < 2:
        return "Yesterday"
    if days < 7:
        return time.strftime("%A", t)
    return time.strftime("%d/%m/%Y", t)


def chat_time(ts):
    """Centred chat timestamp: "Today 14:32", "Yesterday 09:01", "Mon 12 Oct 18:20"."""
    label = list_time(ts)
    t = time.localtime(ts)
    if ":" in label:
        return "Today " + label
    if label == "Yesterday" or "/" not in label:
        return "%s %s" % (label, time.strftime("%H:%M", t))
    return time.strftime("%a %d %b %H:%M", t)


REPLY_RE = re.compile(r'^reply:\s*["“](.*?)["”]\s*\n(.+)$', re.S | re.I)


# The iPhone doesn't share pictures over Bluetooth; it sends the text "Attachment: 1 Image" instead
ATTACHMENT_RE = re.compile(r"^[ \t]*Attachments?:[ \t]*(.+?)[ \t]*$", re.I | re.M)
ATTACHMENT_KINDS = {  # word the iPhone uses: (emoji, one, many)
    "image": ("📷", "Photo", "Photos"),
    "photo": ("📷", "Photo", "Photos"),
    "video": ("🎥", "Video", "Videos"),
    "audio": ("🎤", "Audio message", "Audio messages"),
    "audio message": ("🎤", "Audio message", "Audio messages"),
    "contact": ("👤", "Contact card", "Contact cards"),
    "location": ("📍", "Location", "Locations"),
}


def split_attachments(text):
    """(text without attachment lines, [(emoji, description)]) for a message."""
    found = []
    for spec in ATTACHMENT_RE.findall(text):
        for part in re.split(r",|\band\b", spec):
            m = re.match(r"\s*(\d+)\s+([A-Za-z ]+?)s?\s*$", part)
            if not m:
                continue
            count, kind = int(m.group(1)), m.group(2).lower()
            emoji, one, many = ATTACHMENT_KINDS.get(kind, ("📎", "Attachment", "Attachments"))
            found.append((emoji, one if count == 1 else "%d %s" % (count, many)))
    if not found:
        return text, []
    return ATTACHMENT_RE.sub("", text).strip(), found


def plain_text(text):
    """A message as one line of text, with attachments as e.g. "📷 Photo"."""
    rest, attachments = split_attachments(text)
    return " ".join([rest] + ["%s %s" % a for a in attachments]).strip()


def snippet(text, length=40):
    """One-line start of a message, used when quoting it in a reply."""
    line = " ".join(plain_text(text).split())
    return line if len(line) <= length else line[:length - 1].rstrip() + "…"


def initials(name):
    words = [w for w in name.replace("+", " ").split() if w[:1].isalpha()]
    if not words:
        return "👤"
    return "".join(w[0] for w in words[:2]).upper()


def avatar(name, size="small", photo=None):
    """Round contact picture: the iPhone's photo if there is one, otherwise initials."""
    label = Gtk.Label(label="" if photo else initials(name),
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    ctx = label.get_style_context()
    ctx.add_class("avatar")
    ctx.add_class(size)
    if photo:
        provider = Gtk.CssProvider()
        provider.load_from_data(('* { background-image: url("%s"); background-size: cover;'
                                 ' background-position: center; }' % Gio.File.new_for_path(photo).get_uri()).encode())
        ctx.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    return label


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Lime")
        self.set_default_size(1000, 720)
        self.store = app.store
        self.client = app.client
        self.cfg = load_config()
        self.current_conv = None
        self.current_address = None
        self.current_name = ""

        # Header bar: device picker and connect button on the left, compose on the right
        header = Gtk.HeaderBar(show_close_button=True, title="Lime")
        header.set_decoration_layout(WINDOW_BUTTON_LAYOUTS[self.cfg.get("window_buttons", "left")])
        self.set_titlebar(header)
        self.header = header
        self.device_combo = Gtk.ComboBoxText(valign=Gtk.Align.CENTER)
        self.device_combo.set_tooltip_text("Your paired iPhone")
        header.pack_start(self.device_combo)
        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh_btn.set_tooltip_text("Reload device list")
        refresh_btn.connect("clicked", lambda b: self.load_devices())
        header.pack_start(refresh_btn)
        self.connect_btn = Gtk.Button(label="Connect", valign=Gtk.Align.CENTER)
        self.connect_btn.get_style_context().add_class("capsule")
        self.connect_btn.connect("clicked", self.on_connect_clicked)
        header.pack_start(self.connect_btn)
        new_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic", Gtk.IconSize.BUTTON)
        new_btn.set_tooltip_text("New message")
        new_btn.connect("clicked", self.on_new_clicked)
        header.pack_end(new_btn)
        settings_btn = Gtk.MenuButton(popover=self.build_settings_popover())
        settings_btn.add(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON))
        settings_btn.set_tooltip_text("Settings")
        header.pack_end(settings_btn)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        self.infobar = Gtk.InfoBar(message_type=Gtk.MessageType.INFO)
        self.info_label = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        self.infobar.get_content_area().add(self.info_label)
        outer.pack_start(self.infobar, False, False, 0)

        paned = Gtk.Paned()
        outer.pack_start(paned, True, True, 0)

        # Sidebar: big "Messages" title, search, conversation list
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.set_size_request(270, -1)
        title = Gtk.Label(label="Messages", xalign=0)
        title.get_style_context().add_class("big-title")
        sidebar.pack_start(title, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text="Search")
        self.search.get_style_context().add_class("search")
        self.search.connect("search-changed", lambda e: self.conv_list.invalidate_filter())
        sidebar.pack_start(self.search, False, False, 0)
        self.conv_list = Gtk.ListBox()
        self.conv_list.connect("row-selected", self.on_conv_selected)
        self.conv_list.connect("button-press-event", self.on_conv_button_press)
        self.conv_list.set_filter_func(self.filter_row)
        conv_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        conv_scroll.get_style_context().add_class("sidebar")
        conv_scroll.add(self.conv_list)
        sidebar.pack_start(conv_scroll, True, True, 0)
        paned.pack1(sidebar, False, False)

        # Chat: header with avatar and name, scrolling bubbles, compose bar
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("chat-bg")
        paned.pack2(right, True, False)

        self.chat_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.chat_header.get_style_context().add_class("chat-header")
        right.pack_start(self.chat_header, False, False, 0)

        self.msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=16, margin_end=16,
                               margin_top=8, margin_bottom=8)
        self.msg_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.msg_scroll.get_style_context().add_class("chat-bg")
        self.msg_scroll.add(self.msg_box)
        right.pack_start(self.msg_scroll, True, True, 0)

        compose = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        compose.get_style_context().add_class("compose")
        self.reply_to = None
        self.reply_bar = Gtk.Box(spacing=6, no_show_all=True)
        self.reply_bar.get_style_context().add_class("reply-bar")
        reply_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.reply_title = Gtk.Label(xalign=0)
        self.reply_title.get_style_context().add_class("reply-bar-title")
        self.reply_snippet = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.reply_snippet.get_style_context().add_class("reply-bar-text")
        reply_text.pack_start(self.reply_title, False, False, 0)
        reply_text.pack_start(self.reply_snippet, False, False, 0)
        reply_close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        reply_close.set_valign(Gtk.Align.CENTER)
        reply_close.set_tooltip_text("Cancel reply (Esc)")
        reply_close.connect("clicked", lambda b: self.cancel_reply())
        self.reply_bar.pack_start(reply_text, True, True, 0)
        self.reply_bar.pack_start(reply_close, False, False, 0)
        for w in (reply_text, self.reply_title, self.reply_snippet, reply_close):
            w.show()
        compose.pack_start(self.reply_bar, False, False, 0)
        pill = Gtk.Box(spacing=4)
        pill.get_style_context().add_class("pill")
        self.entry = Gtk.Entry(placeholder_text="iMessage", has_frame=False)
        self.entry.connect("activate", self.on_send)
        self.entry.connect("changed", lambda e: self.update_send_button())
        self.entry.connect("key-press-event", self.on_entry_key)
        self.send_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.send_btn.add(Gtk.Image.new_from_icon_name("go-up-symbolic", Gtk.IconSize.BUTTON))
        self.send_btn.get_style_context().add_class("send-btn")
        self.send_btn.set_tooltip_text("Send")
        self.send_btn.connect("clicked", self.on_send)
        pill.pack_start(self.entry, True, True, 0)
        pill.pack_start(self.send_btn, False, False, 0)
        compose.pack_start(pill, True, True, 0)
        right.pack_start(compose, False, False, 0)
        self.compose = compose

        self.client.connect("state-changed", self.on_state_changed)
        self.connect("notify::is-active", self.on_focus_changed)
        self.load_devices()
        self.reload_conversations()
        self.show_all()
        self.show_chat_header()
        self.compose.set_visible(False)
        self.on_state_changed(self.client, self.client.state, "")

    # -- devices / connection ---------------------------------------------

    def build_settings_popover(self):
        grid = Gtk.Grid(row_spacing=8, column_spacing=12, margin=12)
        title = Gtk.Label(label="Settings", xalign=0)
        title.get_style_context().add_class("settings-title")
        grid.attach(title, 0, 0, 2, 1)
        section = Gtk.Label(label="Bubble colours", xalign=0)
        section.get_style_context().add_class("settings-section")
        grid.attach(section, 0, 1, 2, 1)
        self.color_buttons = {}
        saved = self.cfg.get("bubble_colors", {})
        for row, (key, text, default) in enumerate(BUBBLE_COLORS, start=2):
            rgba = Gdk.RGBA()
            rgba.parse(saved.get(key, default))
            btn = Gtk.ColorButton(rgba=rgba, title=text)
            btn.connect("color-set", self.on_bubble_color_set, key)
            self.color_buttons[key] = btn
            grid.attach(Gtk.Label(label=text, xalign=0), 0, row, 1, 1)
            grid.attach(btn, 1, row, 1, 1)
        reset = Gtk.Button(label="Reset to defaults")
        reset.connect("clicked", self.on_bubble_colors_reset)
        row = len(BUBBLE_COLORS) + 2
        grid.attach(reset, 0, row, 2, 1)
        section = Gtk.Label(label="Window buttons", xalign=0)
        section.get_style_context().add_class("settings-section")
        grid.attach(section, 0, row + 1, 2, 1)
        side = Gtk.ComboBoxText()
        side.append("left", "Left")
        side.append("right", "Right")
        side.set_active_id(self.cfg.get("window_buttons", "left"))
        side.connect("changed", self.on_window_buttons_changed)
        grid.attach(Gtk.Label(label="Side", xalign=0), 0, row + 2, 1, 1)
        grid.attach(side, 1, row + 2, 1, 1)
        grid.show_all()
        popover = Gtk.Popover()
        popover.add(grid)
        return popover

    def on_window_buttons_changed(self, combo):
        side = combo.get_active_id()
        self.cfg["window_buttons"] = side
        save_config(self.cfg)
        self.header.set_decoration_layout(WINDOW_BUTTON_LAYOUTS[side])

    def on_bubble_color_set(self, btn, key):
        self.cfg.setdefault("bubble_colors", {})[key] = btn.get_rgba().to_string()
        save_config(self.cfg)
        self.get_application().apply_bubble_colors(self.cfg["bubble_colors"])

    def on_bubble_colors_reset(self, btn):
        self.cfg.pop("bubble_colors", None)
        save_config(self.cfg)
        for key, _, default in BUBBLE_COLORS:
            rgba = Gdk.RGBA()
            rgba.parse(default)
            self.color_buttons[key].set_rgba(rgba)
        self.get_application().apply_bubble_colors({})

    def load_devices(self):
        self.device_combo.remove_all()
        devices = paired_devices()
        for addr, name in devices:
            self.device_combo.append(addr, name)
        if not devices:
            self.device_combo.append("", "No paired iPhone")
            self.device_combo.set_active(0)
        elif not self.device_combo.set_active_id(self.cfg.get("device", "")):
            self.device_combo.set_active(0)

    def on_connect_clicked(self, btn):
        if self.client.state == "disconnected":
            address = self.device_combo.get_active_id()
            if not address:
                self.show_info(SETUP_HELP, Gtk.MessageType.WARNING)
                return
            self.cfg["device"] = address
            self.cfg["auto_connect"] = True
            save_config(self.cfg)
            self.client.connect_device(address)
        else:
            self.cfg["auto_connect"] = False
            save_config(self.cfg)
            self.client.disconnect_device()

    def on_state_changed(self, client, state, detail):
        if state == "connected":
            self.header.set_subtitle("Connected to iPhone")
            self.connect_btn.set_label("Disconnect")
            self.connect_btn.get_style_context().remove_class("suggested")
            self.infobar.hide()
        elif state == "connecting":
            self.header.set_subtitle("Connecting…")
            self.connect_btn.set_label("Cancel")
            self.connect_btn.get_style_context().remove_class("suggested")
            self.show_info("Connecting to your iPhone… If the iPhone asks to allow notifications, tap Allow.")
        else:
            self.header.set_subtitle("Not connected")
            self.connect_btn.set_label("Connect")
            self.connect_btn.get_style_context().add_class("suggested")
            text = SETUP_HELP
            if detail:
                text = "<b>%s</b>\n\n%s" % (GLib.markup_escape_text(detail), SETUP_HELP)
            self.show_info(text, Gtk.MessageType.WARNING)
        self.update_send_button()

    def show_info(self, markup, kind=Gtk.MessageType.INFO):
        self.info_label.set_markup(markup)
        self.infobar.set_message_type(kind)
        self.infobar.show_all()

    def update_send_button(self):
        self.send_btn.set_sensitive(self.client.state == "connected" and bool(self.entry.get_text().strip()))

    # -- conversations ----------------------------------------------------

    def filter_row(self, row):
        query = self.search.get_text().strip().lower()
        return not query or query in row.display.lower() or query in row.preview.lower() \
            or query in (row.address or "").lower()

    def build_contact_list(self, entry):
        """Alphabetical phone book for the New Message window, filtered by what's typed in entry."""
        contacts = Gtk.ListBox()

        def matches(row):
            query = entry.get_text().strip().lower()
            return not query or query in row.display.lower() or query in row.address.lower()

        def first_letter(row):
            return row.display[:1].upper() if row.display[:1].isalpha() else "#"

        def letter_header(row, before):
            if before and first_letter(before) == first_letter(row):
                row.set_header(None)
                return
            header = Gtk.Label(label=first_letter(row), xalign=0)
            header.get_style_context().add_class("contact-letter")
            row.set_header(header)

        contacts.set_filter_func(matches)
        contacts.set_header_func(letter_header)
        entry.connect("search-changed", lambda e: contacts.invalidate_filter())
        rows = self.store.contacts()
        for c in rows:
            row = Gtk.ListBoxRow()
            row.conv = c["key"]
            row.address = c["address"] or c["key"]  # contacts synced before full numbers were kept
            row.display = c["name"]
            box = Gtk.Box(spacing=10, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
            photo = c["photo"] if c["photo"] and os.path.exists(c["photo"]) else None
            box.pack_start(avatar(row.display, photo=photo), False, False, 0)
            grid = Gtk.Grid(row_spacing=1, valign=Gtk.Align.CENTER)
            name = Gtk.Label(label=row.display, xalign=0, hexpand=True,
                             ellipsize=Pango.EllipsizeMode.END)
            name.get_style_context().add_class("conv-name")
            number = Gtk.Label(label=row.address, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            number.get_style_context().add_class("conv-preview")
            grid.attach(name, 0, 0, 1, 1)
            grid.attach(number, 0, 1, 1, 1)
            box.pack_start(grid, True, True, 0)
            row.add(box)
            contacts.add(row)
        if rows:
            empty = Gtk.Label(label="No matching contacts.\nPress Start to message what you typed.")
        else:
            empty = Gtk.Label(label="No contacts yet. To see your phone book here, on the iPhone go to\n"
                                    "Settings → Bluetooth → ⓘ next to this laptop → Sync Contacts.")
        empty.set_justify(Gtk.Justification.CENTER)
        empty.set_margin_top(24)
        empty.get_style_context().add_class("empty-chat")
        empty.show()
        contacts.set_placeholder(empty)
        return contacts

    def open_contact(self, conv, address, display):
        # select the existing conversation if there is one, otherwise start a new one
        for conv_row in self.conv_list.get_children():
            if conv_row.conv == conv:
                self.conv_list.select_row(conv_row)
                return
        self.conv_list.unselect_all()
        self.open_conversation(conv, address, display)

    def reload_conversations(self):
        for child in self.conv_list.get_children():
            self.conv_list.remove(child)
        selected = None
        total_unread = 0
        for c in self.store.conversations():
            row = Gtk.ListBoxRow()
            row.conv = c["conv"]
            row.address = c["address"]
            row.display = c["name"] or c["address"]
            found = REPLY_RE.match(c["text"])
            row.preview = plain_text(found.group(2) if found else c["text"]).replace("\n", " ")
            box = Gtk.Box(spacing=10, margin_start=4, margin_end=8, margin_top=10, margin_bottom=10)
            dot = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            dot.get_style_context().add_class("unread-dot")
            if not c["unread"]:
                dot.get_style_context().add_class("read")
            box.pack_start(dot, False, False, 0)
            box.pack_start(avatar(row.display, photo=c["photo"]), False, False, 0)
            grid = Gtk.Grid(column_spacing=6, row_spacing=1, valign=Gtk.Align.CENTER)
            name = Gtk.Label(label=row.display, xalign=0, hexpand=True,
                             ellipsize=Pango.EllipsizeMode.END)
            name.get_style_context().add_class("conv-name")
            when = Gtk.Label(label=list_time(c["ts"]) + "  ›")
            when.get_style_context().add_class("conv-time")
            preview = Gtk.Label(label=row.preview, xalign=0, yalign=0, wrap=True,
                                wrap_mode=Pango.WrapMode.WORD_CHAR, lines=2,
                                ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
            preview.set_size_request(-1, 34)
            preview.get_style_context().add_class("conv-preview")
            if c["unread"]:
                preview.get_style_context().add_class("unread")
            total_unread += c["unread"]
            grid.attach(name, 0, 0, 1, 1)
            grid.attach(when, 1, 0, 1, 1)
            grid.attach(preview, 0, 1, 2, 1)
            box.pack_start(grid, True, True, 0)
            row.add(box)
            self.conv_list.add(row)
            if c["conv"] == self.current_conv:
                selected = row
        self.conv_list.show_all()
        title = "Lime (%d)" % total_unread if total_unread else "Lime"
        self.header.set_title(title)
        self.set_title(title)
        if selected:
            self.conv_list.handler_block_by_func(self.on_conv_selected)
            self.conv_list.select_row(selected)
            self.conv_list.handler_unblock_by_func(self.on_conv_selected)

    def on_focus_changed(self, win, pspec):
        if self.is_active() and self.current_conv and self.store.mark_read(self.current_conv):
            self.reload_conversations()

    def on_conv_selected(self, listbox, row):
        if row is None:
            return
        self.open_conversation(row.conv, row.address, row.display)

    def on_conv_button_press(self, listbox, event):
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != Gdk.BUTTON_SECONDARY:
            return False
        row = listbox.get_row_at_y(int(event.y))
        if row is None:
            return False
        menu = Gtk.Menu()
        delete = Gtk.MenuItem(label="Delete Conversation…")
        delete.connect("activate", lambda item: self.confirm_delete_conversation(row.conv, row.display))
        menu.append(delete)
        menu.show_all()
        menu.attach_to_widget(listbox, None)
        menu.popup_at_pointer(event)
        return True

    def confirm_delete_conversation(self, conv, display):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text="Delete your conversation with %s?" % display)
        dialog.format_secondary_text("This removes the messages from this laptop. "
                                     "They stay on your iPhone.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        delete = dialog.add_button("Delete", Gtk.ResponseType.OK)
        delete.get_style_context().add_class("destructive-action")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.store.delete_conversation(conv)
        if conv == self.current_conv:
            self.current_conv = None
            self.current_address = None
            self.current_name = ""
            self.cancel_reply()
            self.show_chat_header()
            self.compose.set_visible(False)
            self.reload_messages()
        self.reload_conversations()

    def open_conversation(self, conv, address, display):
        self.current_conv = conv
        self.current_address = address
        self.current_name = display
        self.cancel_reply()
        self.show_chat_header()
        self.compose.set_visible(True)
        if self.store.mark_read(conv):
            # defer: this can run inside the sidebar's row-selected handler, and rebuilding
            # the list there destroys the row GTK is still handling the click for (segfault)
            GLib.idle_add(self.reload_conversations)
        self.reload_messages()
        self.entry.grab_focus()

    def show_chat_header(self):
        for child in self.chat_header.get_children():
            self.chat_header.remove(child)
        if self.current_conv:
            photo = self.store.contact_photo(self.current_address)
            self.chat_header.pack_start(avatar(self.current_name, "large", photo), False, False, 0)
            name = Gtk.Label(label=self.current_name + " ›")
            name.get_style_context().add_class("chat-header-name")
            self.chat_header.pack_start(name, False, False, 0)
            if self.current_name != self.current_address:
                addr = Gtk.Label(label=self.current_address)
                addr.get_style_context().add_class("chat-header-address")
                self.chat_header.pack_start(addr, False, False, 0)
            self.chat_header.show_all()
        else:
            self.chat_header.hide()

    def reload_messages(self):
        for child in self.msg_box.get_children():
            self.msg_box.remove(child)
        msgs, badges = self.fold_reactions(self.store.messages(self.current_conv) if self.current_conv else [])
        if not msgs:
            empty = Gtk.Label(label="No messages yet", vexpand=True)
            empty.get_style_context().add_class("empty-chat")
            self.msg_box.pack_start(empty, True, True, 0)
        last_out = max((i for i, m in enumerate(msgs) if m["outgoing"]), default=None)
        for i, m in enumerate(msgs):
            prev = msgs[i - 1] if i else None
            nxt = msgs[i + 1] if i + 1 < len(msgs) else None
            if prev is None or m["ts"] - prev["ts"] > TIMESTAMP_GAP:
                stamp = Gtk.Label(label=chat_time(m["ts"]))
                stamp.get_style_context().add_class("timestamp")
                self.msg_box.pack_start(stamp, False, False, 0)
                prev = None
            starts_group = prev is None or prev["outgoing"] != m["outgoing"] or m["ts"] - prev["ts"] > GROUP_GAP
            ends_group = nxt is None or nxt["outgoing"] != m["outgoing"] or nxt["ts"] - m["ts"] > GROUP_GAP \
                or nxt["ts"] - m["ts"] > TIMESTAMP_GAP
            self.add_bubble(m, starts_group, ends_group, show_receipt=(i == last_out),
                            reacts=badges.get(m["id"]))
        self.msg_box.show_all()
        GLib.idle_add(self.scroll_to_bottom)

    def fold_reactions(self, msgs):
        """Split reaction messages out; returns (messages to show, {message id: [(emoji, mine)]})."""
        shown, badges = [], {}
        for m in msgs:
            found = None
            if m["reaction"] and m["reply_to"]:  # sent from Lime
                found = (m["reaction"], m["reply_to"], False)
            else:
                r = reactions.parse(m["text"])
                target = r and reactions.find_target(shown, r.quote)
                if target:
                    found = (r.emoji, target, r.removed)
            if not found:
                shown.append(m)
                continue
            if m["status"] == "failed":
                continue
            emoji, target, removed = found
            mine = bool(m["outgoing"])
            # like iMessage, each side has at most one reaction per message
            entries = [e for e in badges.get(target, []) if e[1] != mine]
            if not removed:
                entries.append((emoji, mine))
            badges[target] = entries
        return shown, badges

    def add_bubble(self, m, starts_group, ends_group, show_receipt, reacts=None):
        outgoing = bool(m["outgoing"])
        align = Gtk.Align.END if outgoing else Gtk.Align.START
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=align,
                          margin_top=8 if starts_group else 2)
        text = m["text"]
        original = self.store.get(m["reply_to"]) if m["reply_to"] else None
        quoted = snippet(original["text"]) if original else None
        found = REPLY_RE.match(text)
        if not original and found:  # a reply in our format, e.g. sent by someone else's Lime
            quoted, text = found.group(1), found.group(2)
        if quoted:
            quote = Gtk.Label(label='reply:"%s"' % quoted, halign=align, xalign=0,
                              ellipsize=Pango.EllipsizeMode.END, max_width_chars=40)
            quote.get_style_context().add_class("reply-quote")
            wrapper.pack_start(quote, False, False, 0)
        text, attachments = split_attachments(text)
        pieces = []
        if text or not attachments:
            pieces.append(Gtk.Label(label=text))
        for emoji, what in attachments:
            card = Gtk.Label()
            card.set_markup('<span size="x-large">%s</span>  <b>%s</b>\n'
                            '<span size="small" alpha="65%%">Open on your iPhone to view</span>'
                            % (emoji, GLib.markup_escape_text(what)))
            card.get_style_context().add_class("attachment")
            pieces.append(card)
        for piece in pieces:
            piece.set_properties(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True,
                                 xalign=0, max_width_chars=48, halign=align)
            piece.set_can_focus(False)
            piece.connect("populate-popup", self.on_bubble_menu, m["id"])
            ctx = piece.get_style_context()
            ctx.add_class("bubble")
            ctx.add_class("out" if outgoing else "in")
            if m["status"] == "failed":
                ctx.add_class("failed")
        if ends_group:
            pieces[-1].get_style_context().add_class("tail")
        if len(pieces) == 1:
            label = pieces[0]
        else:  # text and attachment cards stack like separate bubbles
            label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=align)
            for piece in pieces:
                label.pack_start(piece, False, False, 0)
        if reacts:
            # badge sits on the bubble's top corner, like a tapback on the iPhone
            overlay = Gtk.Overlay(halign=align)
            holder = Gtk.Box(margin_top=14, halign=align)
            if outgoing:
                holder.set_margin_start(14)
            else:
                holder.set_margin_end(14)
            holder.pack_start(label, False, False, 0)
            overlay.add(holder)
            badge = Gtk.Label(label="".join(e for e, _ in reacts), valign=Gtk.Align.START,
                              halign=Gtk.Align.START if outgoing else Gtk.Align.END)
            badge.get_style_context().add_class("reaction-badge")
            if any(mine for _, mine in reacts):
                badge.get_style_context().add_class("mine")
            overlay.add_overlay(badge)
            wrapper.pack_start(overlay, False, False, 0)
        else:
            wrapper.pack_start(label, False, False, 0)

        receipt = None
        if m["status"] == "failed":
            receipt = Gtk.Label(label="Not Delivered  ⓘ", halign=align)
            receipt.get_style_context().add_class("receipt-error")
        elif m["status"] == "sending":
            receipt = Gtk.Label(label="Sending…", halign=align)
        elif show_receipt:
            receipt = Gtk.Label(label="Sent", halign=align)
        if receipt:
            receipt.get_style_context().add_class("receipt")
            wrapper.pack_start(receipt, False, False, 0)
        wrapper.set_tooltip_text(time.strftime("%a %d %b %Y, %H:%M", time.localtime(m["ts"])))
        self.msg_box.pack_start(wrapper, False, False, 0)

    def scroll_to_bottom(self):
        adj = self.msg_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def on_contacts_updated(self):
        self.reload_conversations()
        if self.current_conv:
            self.current_name = self.store.contact_name(self.current_address) or self.current_name
            self.show_chat_header()

    def on_message_stored(self, conv):
        if conv == self.current_conv and self.is_active():
            self.store.mark_read(conv)  # arrived while you were looking at it
        self.reload_conversations()
        if conv == self.current_conv:
            self.reload_messages()

    # -- sending ----------------------------------------------------------

    def on_new_clicked(self, btn):
        dialog = Gtk.Dialog(title="New Message", transient_for=self, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Start", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_default_size(420, 560)
        box = dialog.get_content_area()
        box.set_spacing(6)
        box.set_border_width(12)
        box.add(Gtk.Label(label="To: pick a contact, or type a phone number with country code\n"
                                "(e.g. +44 7700 900123) or the email address of an iMessage contact",
                          xalign=0))
        entry = Gtk.SearchEntry(activates_default=True, placeholder_text="Name, number or email")
        entry.get_style_context().add_class("search")
        box.add(entry)
        contacts = self.build_contact_list(entry)
        chosen = []
        contacts.connect("row-activated",
                         lambda listbox, row: (chosen.append(row), dialog.response(Gtk.ResponseType.OK)))
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.get_style_context().add_class("sidebar")
        scroll.add(contacts)
        box.pack_start(scroll, True, True, 0)
        dialog.show_all()
        response = dialog.run()
        typed = entry.get_text().strip()
        if not chosen and typed and not re.search(r"[\d@]", typed):
            # a name was typed: use the first contact it matches
            chosen = [r for r in contacts.get_children() if r.get_child_visible()][:1]
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        if chosen:
            self.open_contact(chosen[0].conv, chosen[0].address, chosen[0].display)
        elif typed:
            self.open_contact(conv_key(typed), typed, self.store.contact_name(typed) or typed)

    def on_send(self, widget):
        text = self.entry.get_text().strip()
        if not text or not self.current_address:
            return
        if self.client.state != "connected":
            self.show_info("<b>Not connected.</b> Connect to your iPhone before sending.",
                           Gtk.MessageType.WARNING)
            return
        reply_to = self.reply_to
        wire_text = text
        if reply_to:  # Bluetooth can't make real threaded replies, so quote the original
            wire_text = 'reply:"%s"\n%s' % (snippet(reply_to["text"]), text)
        self.cancel_reply()
        self.entry.set_text("")
        self.send_text(wire_text, text, reply_to=reply_to["id"] if reply_to else None)

    def send_reaction(self, msg_id, emoji):
        target = self.store.get(msg_id)
        if not target:
            return
        if self.client.state != "connected":
            self.show_info("<b>Not connected.</b> Connect to your iPhone before reacting.",
                           Gtk.MessageType.WARNING)
            return
        text = reactions.wire_text(emoji, target["text"])
        self.send_text(text, text, reply_to=msg_id, reaction=emoji)

    def send_text(self, wire_text, store_text, reply_to=None, reaction=None):
        """Store a message as "sending", have the phone send it, then record the result."""
        conv = self.current_conv
        address = self.current_address
        msg_id = self.store.add(address, store_text, outgoing=True, status="sending",
                                reply_to=reply_to, reaction=reaction)
        self.on_message_stored(conv)

        def done(ok, error):
            self.store.set_status(msg_id, "sent" if ok else "failed")
            if not ok:
                self.show_info("<b>Message not sent:</b> %s" % GLib.markup_escape_text(error or "unknown error"),
                               Gtk.MessageType.ERROR)
            self.on_message_stored(conv)

        self.client.send(address, wire_text, done)

    # -- replies ----------------------------------------------------------

    def on_bubble_menu(self, label, menu, msg_id):
        react = Gtk.MenuItem(label="React")
        choices = Gtk.Menu()
        for emoji, verb, _ in reactions.TAPBACKS:
            item = Gtk.MenuItem(label="%s   %s" % (emoji, verb.replace(" at", "")))
            item.connect("activate", lambda i, e=emoji: self.send_reaction(msg_id, e))
            choices.append(item)
        react.set_submenu(choices)
        reply = Gtk.MenuItem(label="Reply")
        reply.connect("activate", lambda i: self.start_reply(msg_id))
        menu.prepend(Gtk.SeparatorMenuItem())
        menu.prepend(reply)
        menu.prepend(react)
        menu.show_all()

    def start_reply(self, msg_id):
        m = self.store.get(msg_id)
        if not m:
            return
        self.reply_to = m
        who = "yourself" if m["outgoing"] else (self.current_name or m["address"])
        self.reply_title.set_text("Replying to " + who)
        self.reply_snippet.set_text(m["text"].replace("\n", " "))
        self.reply_bar.show()
        self.entry.grab_focus()

    def cancel_reply(self):
        self.reply_to = None
        self.reply_bar.hide()

    def on_entry_key(self, entry, event):
        if event.keyval == Gdk.KEY_Escape and self.reply_to:
            self.cancel_reply()
            return True
        return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.notifications = []  # notification actions only fire while referenced

    def do_startup(self):
        Gtk.Application.do_startup(self)
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        Notify.init("Lime")
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        titlebuttons = Gtk.CssProvider()
        titlebuttons.load_from_data(TITLEBUTTON_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), titlebuttons,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        # user-chosen bubble colours, layered over the default palette
        self.bubble_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.bubble_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.apply_bubble_colors(load_config().get("bubble_colors", {}))
        self.store =Store(os.path.join(DATA_DIR, "messages.db"))
        self.client = MapClient(CACHE_DIR, self.store.has_handle)
        self.client.connect("message-received", self.on_message_received)
        self.client.connect("state-changed", self.on_client_state)
        self.contact_sync = ContactSync(self.client, CACHE_DIR)
        GLib.timeout_add_seconds(RECONNECT_SECONDS, self.auto_reconnect)
        self.hold()  # keep receiving messages while the window is closed

    def do_activate(self):
        if not self.window:
            self.window = Window(self)
            self.window.connect("destroy", self.on_window_destroyed)
            self.auto_reconnect()
        self.window.present()

    def apply_bubble_colors(self, colors):
        self.bubble_provider.load_from_data(bubble_css(colors))

    def on_window_destroyed(self, win):
        self.window = None

    def auto_reconnect(self):
        cfg = load_config()
        if self.client.state == "disconnected" and cfg.get("auto_connect") and cfg.get("device"):
            self.client.connect_device(cfg["device"])
        return True

    def on_client_state(self, client, state, detail):
        if state == "connected":
            self.contact_sync.run(client.address, self.on_contacts)

    def on_contacts(self, contacts, error):
        if contacts:
            self.store.replace_contacts(self.save_photos(contacts))
            if self.window:
                self.window.on_contacts_updated()
        elif self.window:  # keep any names we already have
            self.window.show_info(CONTACTS_HELP + (
                "\n<small>%s</small>" % GLib.markup_escape_text(error) if error else ""))

    def save_photos(self, contacts):
        """Write contact photos to disk; returns {key: (name, photo path or None, address)}."""
        os.makedirs(AVATAR_DIR, exist_ok=True)
        result, keep = {}, set()
        for key, (name, photo, address) in contacts.items():
            path = None
            if photo:
                # named by content, so a changed photo gets a new URL and isn't served from cache
                path = os.path.join(AVATAR_DIR, hashlib.sha1(photo).hexdigest() + ".jpg")
                if not os.path.exists(path):
                    with open(path, "wb") as f:
                        f.write(photo)
                keep.add(os.path.basename(path))
            result[key] = (name, path, address)
        for old in os.listdir(AVATAR_DIR):
            if old not in keep:
                os.unlink(os.path.join(AVATAR_DIR, old))
        return result

    def on_message_received(self, client, m):
        msg_id = self.store.add(m["address"], m["text"], m["outgoing"], name=m["name"],
                                ts=m["ts"], handle=m["handle"])
        if msg_id is None:
            return
        conv = conv_key(m["address"])
        if self.window:
            self.window.on_message_stored(conv)
        recent = time.time() - m["ts"] < 600
        viewing = self.window and self.window.is_active() and self.window.current_conv == conv
        if not m["outgoing"] and recent and not viewing:
            title = self.store.contact_name(m["address"]) or m["name"] or m["address"]
            icon = self.store.contact_photo(m["address"]) or "mail-message-new"
            note = Notify.Notification.new(title, plain_text(m["text"]), icon)
            note.add_action("default", "Open", self.on_notification_clicked, conv)
            note.connect("closed", lambda n: self.notifications.remove(n))
            self.notifications.append(note)
            note.show()

    def on_notification_clicked(self, note, action, conv):
        self.activate()
        for row in self.window.conv_list.get_children():
            if row.conv == conv:
                self.window.conv_list.select_row(row)


def main():
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Lime")
    Gtk.Window.set_default_icon_name(APP_ID)
    app = App()
    quit_action = Gio.SimpleAction.new("quit", None)
    quit_action.connect("activate", lambda *a: app.quit())
    app.add_action(quit_action)
    app.set_accels_for_action("app.quit", ["<Control>q"])
    return app.run(sys.argv)
