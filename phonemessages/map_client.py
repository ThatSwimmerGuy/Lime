"""Talks to the iPhone's Bluetooth Message Access Profile (MAP) through BlueZ's obexd.

The phone itself sends every message pushed here, exactly like Phone Link or a
car stereo does it.
"""
import os
import re
import tempfile
import time

from gi.repository import Gio, GLib, GObject

from . import bmessage

OBEX = "org.bluez.obex"
CLIENT_PATH = "/org/bluez/obex"
CLIENT_IFACE = "org.bluez.obex.Client1"
MAP_IFACE = "org.bluez.obex.MessageAccess1"
MSG_IFACE = "org.bluez.obex.Message1"
TRANSFER_IFACE = "org.bluez.obex.Transfer1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"


def describe_error(err):
    msg = err.message if isinstance(err, GLib.Error) else str(err)
    if "ServiceUnknown" in msg or "org.bluez.obex was not provided" in msg:
        return "The Bluetooth OBEX service isn't installed (install bluez-obex)."
    if "Host is down" in msg or "Connection refused" in msg or "Timeout" in msg or "timed out" in msg.lower():
        return "Couldn't reach the iPhone. Is Bluetooth on and is it nearby?"
    if "Permission" in msg or "Not Authorized" in msg:
        return "The iPhone refused access. Turn on 'Show Notifications' for this laptop in the iPhone's Bluetooth settings."
    return re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", msg)


def paired_devices():
    """[(address, name)] of paired Bluetooth devices, phones first."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
        reply = bus.call_sync("org.bluez", "/", OM_IFACE, "GetManagedObjects", None, None,
                              Gio.DBusCallFlags.NONE, 5000, None)
    except GLib.Error:
        return []
    devices = []
    for path, ifaces in reply.unpack()[0].items():
        dev = ifaces.get("org.bluez.Device1")
        if dev and dev.get("Paired"):
            is_phone = dev.get("Icon", "").startswith("phone")
            devices.append((not is_phone, dev.get("Alias") or dev.get("Name") or dev["Address"], dev["Address"]))
    return [(addr, name) for _, name, addr in sorted(devices)]


class MapClient(GObject.Object):
    __gsignals__ = {
        # state ("disconnected" / "connecting" / "connected"), detail text
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        # dict with handle, address, name, outgoing, text, ts
        "message-received": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, cache_dir, is_known):
        super().__init__()
        self.cache_dir = cache_dir
        self.is_known = is_known  # (handle, ts) -> bool, skips messages already stored
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.session = None
        self.address = None
        self.state = "disconnected"
        self._queue = []
        self._fetching = False
        self._seen = set()
        self.bus.signal_subscribe(None, OM_IFACE, "InterfacesAdded", None, None,
                                  Gio.DBusSignalFlags.NONE, self._on_interfaces_added)
        self.bus.signal_subscribe(None, OM_IFACE, "InterfacesRemoved", None, None,
                                  Gio.DBusSignalFlags.NONE, self._on_interfaces_removed)

    # -- plumbing ---------------------------------------------------------

    def _set_state(self, state, detail=""):
        self.state = state
        self.emit("state-changed", state, detail)

    def _call(self, path, iface, method, args, cb, timeout=30000):
        params = GLib.Variant(*args) if args else None

        def done(bus, res):
            try:
                value = bus.call_finish(res).unpack()
            except GLib.Error as e:
                cb(None, e)
                return
            cb(value, None)

        self.bus.call(OBEX, path, iface, method, params, None, Gio.DBusCallFlags.NONE,
                      timeout, None, done)

    def _wait_transfer(self, value, err, finished, timeout=90):
        """Wait for an obexd Transfer1 object to finish, then call finished(ok, error)."""
        if err:
            finished(False, describe_error(err))
            return
        tpath, props = value
        done = {"flag": False}

        def complete(ok, error=None):
            if done["flag"]:
                return
            done["flag"] = True
            self.bus.signal_unsubscribe(sub)
            GLib.source_remove(timer)
            finished(ok, error)

        def on_changed(bus, sender, path, iface, signal, params):
            _, changed, _ = params.unpack()
            status = changed.get("Status")
            if status == "complete":
                complete(True)
            elif status == "error":
                complete(False, "The phone reported an error.")

        def on_status(value, err):
            if err:  # obexd removes finished transfers, so a missing object means done
                if "UnknownObject" in err.message or "doesn't exist" in err.message:
                    complete(True)
                return
            if value[0] == "complete":
                complete(True)
            elif value[0] == "error":
                complete(False, "The phone reported an error.")

        def on_timeout():
            complete(False, "Timed out waiting for the phone.")
            return False

        sub = self.bus.signal_subscribe(None, PROPS_IFACE, "PropertiesChanged", tpath, TRANSFER_IFACE,
                                        Gio.DBusSignalFlags.NONE, on_changed)
        timer = GLib.timeout_add_seconds(timeout, on_timeout)
        if props.get("Status") == "complete":
            complete(True)
        else:  # it may have finished before we subscribed
            self._call(tpath, PROPS_IFACE, "Get", ("(ss)", (TRANSFER_IFACE, "Status")), on_status)

    # -- connection -------------------------------------------------------

    def connect_device(self, address):
        if self.state != "disconnected":
            return
        self.address = address
        self._set_state("connecting", address)
        self._call(CLIENT_PATH, CLIENT_IFACE, "CreateSession",
                   ("(sa{sv})", (address, {"Target": GLib.Variant("s", "map")})),
                   self._on_session_created, timeout=60000)

    def disconnect_device(self):
        if self.session:
            self._call(CLIENT_PATH, CLIENT_IFACE, "RemoveSession", ("(o)", (self.session,)),
                       lambda v, e: None)
        self._drop_session("Disconnected")

    def _drop_session(self, detail):
        self.session = None
        self._queue.clear()
        self._seen.clear()
        self._fetching = False
        self._set_state("disconnected", detail)

    def _on_session_created(self, value, err):
        if err:
            self._set_state("disconnected", describe_error(err))
            return
        if self.state != "connecting":  # cancelled while we were waiting
            self._call(CLIENT_PATH, CLIENT_IFACE, "RemoveSession", ("(o)", value), lambda v, e: None)
            return
        self.session = value[0]
        self._call(self.session, MAP_IFACE, "SetFolder", ("(s)", ("/telecom/msg",)), self._on_folder_set)

    def _on_folder_set(self, value, err):
        if err:
            self.disconnect_device()
            self._set_state("disconnected", describe_error(err))
            return
        self._set_state("connected", "")
        self.refresh()

    def refresh(self):
        """Ask the phone for whatever recent messages it is willing to share."""
        if not self.session:
            return
        filt = {"MaxCount": GLib.Variant("q", 500), "SubjectLength": GLib.Variant("y", 255)}
        for folder in ("inbox", "sent"):
            self._call(self.session, MAP_IFACE, "ListMessages", ("(sa{sv})", (folder, filt)),
                       self._on_listed)

    def _on_listed(self, value, err):
        if err:  # the iPhone doesn't offer every folder; that's fine
            return
        listing = value[0]
        for path in sorted(listing, key=lambda p: listing[p].get("Timestamp", "")):
            self._enqueue(path)

    def _on_interfaces_added(self, bus, sender, path, iface, signal, params):
        obj, ifaces = params.unpack()
        if self.session and obj.startswith(self.session + "/") and MSG_IFACE in ifaces:
            self._enqueue(obj)  # new message notification from the phone

    def _on_interfaces_removed(self, bus, sender, path, iface, signal, params):
        obj, _ = params.unpack()
        if self.session and obj == self.session:
            self._drop_session("The iPhone disconnected.")

    # -- reading ----------------------------------------------------------

    def _enqueue(self, path):
        if path in self._seen:
            return
        self._seen.add(path)
        self._queue.append(path)
        self._pump()

    def _pump(self):
        if self._fetching or not self._queue or not self.session:
            return
        self._fetching = True
        path = self._queue.pop(0)

        def next_one():
            self._fetching = False
            self._pump()

        def on_props(props, err):
            if err:
                next_one()
                return
            props = props[0]
            handle = os.path.basename(path)
            ts = bmessage.parse_timestamp(props.get("Timestamp"))
            if ts and self.is_known(handle, ts):
                next_one()
                return
            target = os.path.join(self.cache_dir, handle + ".bmsg")

            def finished(ok, error):
                data = b""
                if ok and os.path.exists(target):
                    with open(target, "rb") as f:
                        data = f.read()
                if os.path.exists(target):
                    os.unlink(target)
                if data or props.get("Subject"):
                    self.emit("message-received", self._make_message(handle, props, data, ts))
                next_one()

            self._call(path, MSG_IFACE, "Get", ("(sb)", (target, False)),
                       lambda v, e: self._wait_transfer(v, e, finished, timeout=30))

        self._call(path, PROPS_IFACE, "GetAll", ("(s)", (MSG_IFACE,)), on_props)

    def _make_message(self, handle, props, data, ts):
        parsed = bmessage.parse(data) if data else {}
        folder = (props.get("Folder") or parsed.get("folder") or "").lower()
        outgoing = "sent" in folder or "outbox" in folder or bool(props.get("Sent") and "inbox" not in folder)
        if outgoing:
            address = props.get("RecipientAddress") or parsed.get("recipient_address") or ""
            name = props.get("Recipient") or parsed.get("recipient_name") or ""
        else:
            address = props.get("SenderAddress") or parsed.get("sender_address") or ""
            name = props.get("Sender") or parsed.get("sender_name") or ""
        if name == address:
            name = ""
        return {
            "handle": handle,
            "address": address or name or "Unknown",
            "name": name,
            "outgoing": outgoing,
            "text": parsed.get("text") or props.get("Subject") or "",
            "ts": ts or time.time(),
        }

    # -- sending ----------------------------------------------------------

    def send(self, address, text, callback):
        """Have the iPhone send `text` to `address`; callback(ok, error)."""
        if not self.session:
            callback(False, "Not connected to the iPhone.")
            return
        fd, path = tempfile.mkstemp(suffix=".bmsg", dir=self.cache_dir)
        with os.fdopen(fd, "wb") as f:
            f.write(bmessage.build(address, text))

        def finished(ok, error):
            os.unlink(path)
            callback(ok, error)

        args = {"Charset": GLib.Variant("s", "utf8"),
                "Transparent": GLib.Variant("b", False),
                "Retry": GLib.Variant("b", True)}
        self._call(self.session, MAP_IFACE, "PushMessage", ("(ssa{sv})", (path, "outbox", args)),
                   lambda v, e: self._wait_transfer(v, e, finished))
