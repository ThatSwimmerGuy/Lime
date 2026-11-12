"""MAP and PBAP clients that speak OBEX themselves over an RFCOMM socket, for systems
without BlueZ's obexd (Windows). They offer the same interface as map_client.MapClient and
contacts.ContactSync, so the app can use either.

On Windows Lime also runs the MAP notification server the phone reports new messages to.
Polling still catches anything the phone doesn't report, and covers Linux testing, where
BlueZ's obexd owns that server.
"""
import queue
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from gi.repository import GLib, GObject

from . import bluetooth, bmessage, obex
from .contacts import parse_vcards
from .map_client import make_message

MAP_TARGET = "bb582b40-420c-11db-b0de-0800200c9a66"
PBAP_TARGET = "796135f0-f0c5-11d8-0966-0800200c9a66"
POLL_SECONDS = 10

# MAP application parameter tags
MAX_LIST_COUNT, FILTER_PERIOD_BEGIN, SUBJECT_LENGTH = 0x01, 0x04, 0x13
ATTACHMENT, TRANSPARENT, RETRY, NOTIFICATION_STATUS, CHARSET = 0x0A, 0x0B, 0x0C, 0x0E, 0x14
UTF8 = 1

# PBAP application parameter tags, and the vCard fields Lime uses
PB_MAX_LIST_COUNT, PB_PROPERTY_SELECTOR, PB_FORMAT = 0x04, 0x06, 0x07
VCARD_FIELDS = 1 << 0 | 1 << 1 | 1 << 2 | 1 << 3 | 1 << 7 | 1 << 8  # VERSION FN N PHOTO TEL EMAIL


def describe_error(err):
    if isinstance(err, obex.ObexError):
        if "Not Authorized" in str(err) or "Forbidden" in str(err):
            return ("The iPhone refused access. Turn on 'Show Notifications' for this computer "
                    "in the iPhone's Bluetooth settings. If that switch isn't there, forget this "
                    "computer on the iPhone and pair again while Lime is open.")
        return str(err)
    if isinstance(err, (TimeoutError, ConnectionRefusedError)) or getattr(err, "winerror", None) in (
            10060, 10061, 10064, 10065, 10050, 10051):
        return "Couldn't reach the iPhone. Is Bluetooth on and is it nearby?"
    if isinstance(err, (ConnectionError, BrokenPipeError)):
        return "The iPhone disconnected."
    return str(err) or err.__class__.__name__


def parse_listing(data, folder):
    """[(handle, obexd-style properties)] from a MAP-msg-listing document."""
    try:
        root = ET.fromstring(data.decode("utf-8", "replace").strip("\0 \r\n"))
    except ET.ParseError:
        return []
    messages = []
    for msg in root.iter("msg"):
        a = msg.attrib
        try:
            number = int(a.get("handle", ""), 16)
        except ValueError:
            continue
        props = {
            "Handle": a["handle"],  # what the phone wants back when asked for the message
            "Folder": "/telecom/msg/" + folder,
            "Subject": a.get("subject", ""),
            "Timestamp": a.get("datetime", ""),
            "Sender": a.get("sender_name", ""),
            "SenderAddress": a.get("sender_addressing", ""),
            "Recipient": a.get("recipient_name", ""),
            "RecipientAddress": a.get("recipient_addressing", ""),
            "Sent": a.get("sent", "").lower() == "yes",
        }
        # obexd names messages "message" + the hex handle in decimal; matching that lets
        # history stored by the obexd client be recognised
        messages.append(("message%d" % number, props))
    return messages


class _Worker:
    """Runs jobs one at a time on a thread of its own; OBEX is strictly request/reply."""

    def __init__(self):
        self.jobs = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            self.jobs.get()()

    def submit(self, job):
        self.jobs.put(job)


class MapClient(GObject.Object):
    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "message-received": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, cache_dir, is_known):
        super().__init__()
        self.cache_dir = cache_dir
        self.is_known = is_known  # only called on the main thread: the store isn't thread-safe
        self.address = None
        self.state = "disconnected"
        self.obex = None
        self._session = 0  # bumped on every connect/disconnect, so stale jobs drop out
        self._seen = set()
        self._poll = None
        self._worker = _Worker()
        self.notifications = False  # whether the phone can report new messages to us
        try:
            server = bluetooth.advertise()
        except OSError as e:
            print("Lime: couldn't publish the Bluetooth services the iPhone looks for: %s" % e)
            server = None
        if server:
            self.notifications = True
            threading.Thread(target=self._serve_notifications, args=(server,), daemon=True).start()

    def _serve_notifications(self, server):
        """Accept the phone's notification connections; each event report triggers a listing."""
        while True:
            try:
                sock = bluetooth.accept(server)
            except OSError:
                return
            def on_put(type_, body):
                if type_ == "x-bt/MAP-event-report":
                    self._main(self._on_event)
            threading.Thread(target=self._serve_one, args=(sock, on_put), daemon=True).start()

    @staticmethod
    def _serve_one(sock, on_put):
        try:
            obex.serve(sock, on_put)
        except (OSError, obex.ObexError):
            pass
        finally:
            sock.close()

    def _on_event(self):
        if self.obex:
            self._list(recent=True)

    # -- plumbing ---------------------------------------------------------

    def _set_state(self, state, detail=""):
        self.state = state
        self.emit("state-changed", state, detail)

    def _main(self, func, *args):
        GLib.idle_add(lambda: func(*args) and False)

    def _job(self, session, func, skipped=None):
        """Run func() on the worker; a failed connection drops the session. skipped() runs
        instead if the session is gone by the time the job's turn comes."""
        def run():
            if session != self._session or not self.obex:
                if skipped:
                    self._main(skipped)
                return
            try:
                func()
            except (OSError, obex.ObexError) as e:
                if isinstance(e, obex.ObexError) and self.obex:
                    self._main(self._report, session, e)
                else:
                    self._main(self._lost, session, describe_error(e))
        self._worker.submit(run)

    def _report(self, session, err):
        if session == self._session:
            print("Lime: %s" % describe_error(err))

    def _lost(self, session, detail):
        if session == self._session and self.state != "disconnected":
            self._drop_session(detail)

    # -- connection -------------------------------------------------------

    def connect_device(self, address):
        if self.state != "disconnected":
            return
        self.address = address
        self._session += 1
        session = self._session
        self._set_state("connecting", address)

        def run():
            try:
                sock = bluetooth.connect(address, bluetooth.MAP_MAS, timeout=60)
                client = obex.Client(sock)
                try:
                    client.connect(MAP_TARGET)
                    client.setpath("")
                    client.setpath("telecom")
                    client.setpath("msg")
                except BaseException:
                    sock.close()
                    raise
            except (OSError, obex.ObexError) as e:
                self._main(self._on_connect_failed, session, describe_error(e))
                return
            self._main(self._on_connected, session, client)
        self._worker.submit(run)

    def _on_connect_failed(self, session, detail):
        if session == self._session:
            self._set_state("disconnected", detail)

    def _on_connected(self, session, client):
        if session != self._session or self.state != "connecting":  # cancelled meanwhile
            self._worker.submit(lambda: self._close(client))
            return
        self.obex = client
        self._set_state("connected", "")
        if self.notifications:
            self._register_notifications(session, client)
        self.refresh()
        self._poll = GLib.timeout_add_seconds(POLL_SECONDS, self._on_poll)

    def _register_notifications(self, session, client):
        """Ask the phone to report new messages to our notification server."""
        def run():
            try:
                client.put(None, "x-bt/MAP-NotificationRegistration", b"0",
                           obex.app_params((NOTIFICATION_STATUS, "B", 1)))
            except obex.ObexError as e:  # polling still works
                print("Lime: the iPhone won't report new messages: %s" % e)
        self._job(session, run)

    @staticmethod
    def _close(client):
        client.disconnect()
        try:
            client.sock.close()
        except OSError:
            pass

    def disconnect_device(self):
        client = self.obex
        if client:
            self._worker.submit(lambda: self._close(client))
        self._drop_session("Disconnected")

    def _drop_session(self, detail):
        self._session += 1
        if self.obex and detail != "Disconnected":
            try:  # wakes the worker if it's stuck waiting on the phone
                self.obex.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.obex.sock.close()
        self.obex = None
        self._seen.clear()
        if self._poll:
            GLib.source_remove(self._poll)
            self._poll = None
        self._set_state("disconnected", detail)

    # -- reading ----------------------------------------------------------

    def _on_poll(self):
        if not self.obex:
            self._poll = None
            return False
        self._list(recent=True)
        return True

    def refresh(self):
        """Ask the phone for whatever recent messages it is willing to share."""
        self._list(recent=False)

    def _list(self, recent):
        if not self.obex:
            return
        session, client = self._session, self.obex
        params = [(MAX_LIST_COUNT, "H", 500), (SUBJECT_LENGTH, "B", 255)]
        if recent:  # only the last day, so a poll stays cheap
            since = (datetime.now() - timedelta(days=1)).strftime("%Y%m%dT%H%M%S").encode()
            params_bytes = obex.app_params(*params) + bytes([FILTER_PERIOD_BEGIN, len(since)]) + since
        else:
            params_bytes = obex.app_params(*params)

        def run():
            found = []
            for folder in ("inbox", "sent"):
                try:
                    body, _ = client.get(folder, "x-bt/MAP-msg-listing", params_bytes)
                except obex.ObexError:  # the iPhone doesn't offer every folder; that's fine
                    continue
                found += parse_listing(body, folder)
            found.sort(key=lambda m: m[1]["Timestamp"])
            self._main(self._on_listed, session, found)
        self._job(session, run)

    def _on_listed(self, session, found):
        if session != self._session:
            return
        for handle, props in found:
            if handle in self._seen:
                continue
            self._seen.add(handle)
            ts = bmessage.parse_timestamp(props.get("Timestamp"))
            if ts and self.is_known(handle, ts):
                continue
            self._fetch(session, handle, props, ts)

    def _fetch(self, session, handle, props, ts):
        client = self.obex

        def run():
            try:
                data, _ = client.get(props["Handle"], "x-bt/message",
                                     obex.app_params((ATTACHMENT, "B", 0), (CHARSET, "B", UTF8)))
            except obex.ObexError:
                data = b""
            if data or props.get("Subject"):
                self._main(self._emit_message, session, make_message(handle, props, data, ts))
        self._job(session, run)

    def _emit_message(self, session, message):
        if session == self._session:
            self.emit("message-received", message)

    # -- sending ----------------------------------------------------------

    def send(self, address, text, callback):
        """Have the iPhone send `text` to `address`; callback(ok, error)."""
        if not self.obex:
            callback(False, "Not connected to the iPhone.")
            return
        session, client = self._session, self.obex
        data = bmessage.build(address, text)
        params = obex.app_params((TRANSPARENT, "B", 0), (RETRY, "B", 1), (CHARSET, "B", UTF8))

        def run():
            try:
                client.put("outbox", "x-bt/message", data, params)
            except (OSError, obex.ObexError) as e:
                self._main(callback, False, describe_error(e))
                if isinstance(e, OSError):
                    raise  # the connection is gone
                return
            self._main(callback, True, None)
        self._job(session, run, skipped=lambda: callback(False, "Not connected to the iPhone."))


class ContactSync:
    """One-shot download of the phonebook; callback(contacts or None, error)."""

    def __init__(self, map_client, cache_dir):
        self.client = map_client
        self.cache_dir = cache_dir
        self.running = False

    def run(self, address, callback):
        if self.running:
            return
        self.running = True

        def finish(contacts, error):
            self.running = False
            callback(contacts, error)

        def work():
            sock = None
            try:
                sock = bluetooth.connect(address, bluetooth.PBAP_PSE, timeout=180)
                client = obex.Client(sock)
                client.connect(PBAP_TARGET)
                params = obex.app_params((PB_PROPERTY_SELECTOR, "Q", VCARD_FIELDS),
                                         (PB_FORMAT, "B", 1), (PB_MAX_LIST_COUNT, "H", 0xFFFF))
                data, _ = client.get("telecom/pb.vcf", "x-bt/phonebook", params)
                client.disconnect()
                result = (parse_vcards(data), None)
            except (OSError, obex.ObexError) as e:
                result = (None, describe_error(e))
            finally:
                if sock:
                    sock.close()
            GLib.idle_add(lambda: finish(*result) and False)

        threading.Thread(target=work, daemon=True).start()

