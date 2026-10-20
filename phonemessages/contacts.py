"""Fetches the iPhone's contacts over Bluetooth PBAP (Phonebook Access) so
conversations can show names and photos instead of numbers."""
import base64
import binascii
import os
import re

from gi.repository import GLib

from .map_client import CLIENT_IFACE, CLIENT_PATH, describe_error
from .store import conv_key

PBAP_IFACE = "org.bluez.obex.PhonebookAccess1"


def parse_vcards(data):
    """{conv_key: (name, photo bytes or None, address as written)} for every phone number and email in a vCard dump."""
    text = data.decode("utf-8", "replace").replace("\r\n", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines
    contacts = {}
    for card in re.findall(r"BEGIN:VCARD\n(.*?)END:VCARD", text, re.S):
        name = ""
        n_field = ""
        photo = None
        addresses = []
        for line in card.splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            prop = key.split(";")[0].split(".")[-1].upper()  # drop params and "item1." groups
            value = value.replace("\\,", ",").replace("\\;", ";").strip()
            if prop == "FN":
                name = value
            elif prop == "N":
                n_field = value
            elif prop == "PHOTO" and value and not value.startswith("http"):
                try:
                    photo = base64.b64decode("".join(value.split()), validate=False)
                except (binascii.Error, ValueError):
                    photo = None
            elif prop in ("TEL", "EMAIL") and value:
                addresses.append(value)
        if not name and n_field:
            parts = [p for p in n_field.split(";") if p]
            name = " ".join(reversed(parts[:2]))
        if not name:
            continue
        for address in addresses:
            key = conv_key(address)
            if key:
                contacts.setdefault(key, (name, photo, address))
    return contacts


class ContactSync:
    """One-shot download of the phonebook; callback(contacts or None, error)."""

    def __init__(self, map_client, cache_dir):
        self.client = map_client  # reuse its D-Bus helpers
        self.cache_dir = cache_dir
        self.running = False

    def run(self, address, callback):
        if self.running:
            return
        self.running = True
        target = os.path.join(self.cache_dir, "phonebook.vcf")
        session = {}

        def finish(contacts, error):
            self.running = False
            if session.get("path"):
                self.client._call(CLIENT_PATH, CLIENT_IFACE, "RemoveSession",
                                  ("(o)", (session["path"],)), lambda v, e: None)
            if os.path.exists(target):
                os.unlink(target)
            callback(contacts, error)

        def on_pulled(ok, error):
            if not ok:
                finish(None, error)
                return
            try:
                with open(target, "rb") as f:
                    finish(parse_vcards(f.read()), None)
            except OSError as e:
                finish(None, str(e))

        def on_selected(value, err):
            if err:
                finish(None, describe_error(err))
                return
            filters = {"Format": GLib.Variant("s", "vcard30"),
                       "Fields": GLib.Variant("as", ["VERSION", "FN", "N", "TEL", "EMAIL", "PHOTO"])}
            self.client._call(session["path"], PBAP_IFACE, "PullAll", ("(sa{sv})", (target, filters)),
                              lambda v, e: self.client._wait_transfer(v, e, on_pulled, timeout=180))

        def on_session(value, err):
            if err:
                finish(None, describe_error(err))
                return
            session["path"] = value[0]
            self.client._call(session["path"], PBAP_IFACE, "Select", ("(ss)", ("int", "pb")), on_selected)

        self.client._call(CLIENT_PATH, CLIENT_IFACE, "CreateSession",
                          ("(sa{sv})", (address, {"Target": GLib.Variant("s", "pbap")})),
                          on_session, timeout=60000)
