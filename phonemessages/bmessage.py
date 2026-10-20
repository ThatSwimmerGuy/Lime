"""Build and parse bMessage documents (the message format used by Bluetooth MAP)."""
import re
from datetime import datetime, timezone

CRLF = "\r\n"


def build(recipient, text, recipient_name=""):
    """Return a bMessage (bytes) asking the phone to send `text` to `recipient`."""
    body = text.replace("\r\n", "\n").replace("\n", CRLF)
    msg = "BEGIN:MSG" + CRLF + body + CRLF + "END:MSG" + CRLF
    lines = [
        "BEGIN:BMSG",
        "VERSION:1.0",
        "STATUS:UNREAD",
        "TYPE:SMS_GSM",
        "FOLDER:telecom/msg/outbox",
        # Originator: left blank, the phone fills in its own identity.
        "BEGIN:VCARD", "VERSION:2.1", "N:", "TEL:", "END:VCARD",
        "BEGIN:BENV",
        "BEGIN:VCARD", "VERSION:2.1", "N:" + recipient_name, "TEL:" + recipient, "END:VCARD",
        "BEGIN:BBODY",
        "CHARSET:UTF-8",
        "LENGTH:%d" % len(msg.encode("utf-8")),
    ]
    tail = ["END:BBODY", "END:BENV", "END:BMSG"]
    return (CRLF.join(lines) + CRLF + msg + CRLF.join(tail) + CRLF).encode("utf-8")


def _vcard(section):
    """Name and address from the first vCard in `section`."""
    m = re.search(r"BEGIN:VCARD\n(.*?)END:VCARD", section, re.S)
    name = address = ""
    if not m:
        return name, address
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields.setdefault(key.split(";")[0].upper(), value.strip())
    name = fields.get("FN", "")
    if not name and fields.get("N"):
        parts = [p for p in fields["N"].split(";") if p]
        name = " ".join(reversed(parts[:2]))
    address = fields.get("TEL") or fields.get("EMAIL", "")
    return name, address


def parse(data):
    """Extract folder, originator, recipient and text from a bMessage."""
    s = data.decode("utf-8", "replace").replace("\r\n", "\n")
    folder = re.search(r"^FOLDER:(.*)$", s, re.M)
    head, _, envelope = s.partition("BEGIN:BENV")
    sender_name, sender_address = _vcard(head)
    recipient_name, recipient_address = _vcard(envelope.split("BEGIN:BBODY")[0])
    parts = re.findall(r"BEGIN:MSG\n(.*?)\nEND:MSG", s, re.S)
    return {
        "folder": folder.group(1).strip() if folder else "",
        "sender_name": sender_name,
        "sender_address": sender_address,
        "recipient_name": recipient_name,
        "recipient_address": recipient_address,
        "text": "\n".join(parts).strip(),
    }


def parse_timestamp(s):
    """MAP timestamps look like 20261019T153000, optionally with Z or +hhmm."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        if len(s) == 20 and s[15] in "+-":
            return datetime.strptime(s, "%Y%m%dT%H%M%S%z").timestamp()
        return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").timestamp()
    except ValueError:
        return None
