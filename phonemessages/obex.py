"""A small OBEX client and server (the protocol under Bluetooth MAP and PBAP), for systems
without BlueZ's obexd. It runs over any connected stream socket, such as an RFCOMM one.

Only what Lime needs: as a client CONNECT with a target, GET, PUT, SETPATH and DISCONNECT;
as a server, accepting the PUTs a phone sends to report new messages.
"""
import struct
import uuid

# opcodes (the 0x80 bit marks the final packet of a request)
CONNECT, DISCONNECT, PUT, GET, SETPATH = 0x80, 0x81, 0x02, 0x03, 0x85
FINAL = 0x80

# response codes, final bit included
CONTINUE, SUCCESS = 0x90, 0xA0

# header ids; the top two bits give the encoding
NAME, TYPE, LENGTH, TARGET, WHO = 0x01, 0x42, 0xC3, 0x46, 0x4A
BODY, END_OF_BODY, APP_PARAMS, CONNECTION_ID = 0x48, 0x49, 0x4C, 0xCB

RESPONSES = {
    0xC0: "Bad request", 0xC1: "Not Authorized", 0xC3: "Forbidden", 0xC4: "Not found",
    0xC6: "Not acceptable", 0xCB: "Gone", 0xCC: "Length required", 0xCD: "Precondition failed",
    0xCF: "Unsupported media type", 0xD0: "Internal server error", 0xD1: "Not implemented",
    0xD3: "Service unavailable",
}


class ObexError(Exception):
    pass


def encode_header(hid, value):
    kind = hid & 0xC0
    if kind == 0x00:  # null-terminated UTF-16BE text; an empty name is just the length
        data = (value + "\0").encode("utf-16-be") if value else b""
        return struct.pack(">BH", hid, 3 + len(data)) + data
    if kind == 0x40:  # byte sequence
        if isinstance(value, str):
            value = value.encode("ascii") + b"\0"  # Type headers are null-terminated ASCII
        return struct.pack(">BH", hid, 3 + len(value)) + value
    if kind == 0x80:
        return struct.pack(">BB", hid, value)
    return struct.pack(">BI", hid, value)


def decode_headers(data):
    """[(id, value)] from the header part of a packet. Text comes back as str, the rest as bytes or int."""
    headers, i = [], 0
    while i < len(data):
        hid = data[i]
        kind = hid & 0xC0
        if kind in (0x00, 0x40):
            (size,) = struct.unpack_from(">H", data, i + 1)
            if size < 3:
                raise ObexError("Malformed reply from the phone.")
            raw = data[i + 3:i + size]
            value = raw.decode("utf-16-be").rstrip("\0") if kind == 0x00 else raw
            i += size
        elif kind == 0x80:
            value = data[i + 1]
            i += 2
        else:
            (value,) = struct.unpack_from(">I", data, i + 1)
            i += 5
        headers.append((hid, value))
    return headers


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("The iPhone disconnected.")
        buf += chunk
    return buf


def read_packet(sock):
    """(opcode or response code, everything after the length) of the next packet."""
    code, size = struct.unpack(">BH", _recv_exact(sock, 3))
    if size < 3:
        raise ObexError("Malformed packet from the phone.")
    return code, _recv_exact(sock, size - 3)


def serve(sock, on_put, max_packet=0xFFFF):
    """Answer one OBEX client until it disconnects. on_put(type, body) is called for each
    finished PUT; that's how a phone delivers MAP event reports."""
    body, type_ = b"", None
    while True:
        try:
            opcode, data = read_packet(sock)
        except ConnectionError:
            return

        def reply(code, headers=(), prefix=b""):
            payload = b"".join(encode_header(h, v) for h, v in headers)
            sock.sendall(struct.pack(">BH", code, 3 + len(prefix) + len(payload)) + prefix + payload)

        if opcode == CONNECT:
            target = dict(decode_headers(data[4:])).get(TARGET)
            headers = [(CONNECTION_ID, 1)] + ([(WHO, target)] if target else [])
            reply(SUCCESS, headers, struct.pack(">BBH", 0x10, 0, max_packet))
        elif opcode in (PUT, PUT | FINAL):
            for hid, value in decode_headers(data):
                if hid in (BODY, END_OF_BODY):
                    body += value
                elif hid == TYPE:
                    type_ = value.rstrip(b"\0").decode("ascii", "replace")
            if opcode & FINAL:
                reply(SUCCESS)
                on_put(type_, body)
                body, type_ = b"", None
            else:
                reply(CONTINUE)
        elif opcode == DISCONNECT:
            reply(SUCCESS)
            return
        else:
            reply(0xD1)  # Not implemented


def app_params(*params):
    """Encode (tag, struct format, value) triples as an Application Parameters body."""
    out = b""
    for tag, fmt, value in params:
        data = struct.pack(">" + fmt, value)
        out += struct.pack(">BB", tag, len(data)) + data
    return out


class Client:
    def __init__(self, sock, max_packet=0xFFFF):
        self.sock = sock
        self.max_packet = max_packet
        self.peer_max = 255  # the minimum every OBEX device accepts, until CONNECT says more
        self.connection_id = None

    # -- wire ---------------------------------------------------------------

    def _request(self, opcode, headers=(), prefix=b""):
        """Send one packet and return (response code, extra prefix bytes, headers)."""
        body = b"".join(encode_header(h, v) for h, v in headers)
        self.sock.sendall(struct.pack(">BH", opcode, 3 + len(prefix) + len(body)) + prefix + body)
        code, rest = read_packet(self.sock)
        if opcode == CONNECT:  # version, flags and max packet length come before the headers
            return code, rest[:4], decode_headers(rest[4:])
        return code, b"", decode_headers(rest)

    def _with_id(self, headers):
        if self.connection_id is None:
            return list(headers)
        return [(CONNECTION_ID, self.connection_id)] + list(headers)

    @staticmethod
    def _check(code, what):
        if code != SUCCESS:
            raise ObexError("%s failed: %s" % (what, RESPONSES.get(code, "error 0x%02X" % code)))

    # -- operations ----------------------------------------------------------

    def connect(self, target):
        """target is a uuid.UUID string such as MAP's or PBAP's service UUID."""
        prefix = struct.pack(">BBH", 0x10, 0, self.max_packet)
        code, info, headers = self._request(CONNECT, [(TARGET, uuid.UUID(target).bytes)], prefix)
        self._check(code, "Connecting")
        self.peer_max = max(255, struct.unpack(">H", info[2:4])[0])
        for hid, value in headers:
            if hid == CONNECTION_ID:
                self.connection_id = value

    def disconnect(self):
        try:
            self._request(DISCONNECT, self._with_id([]))
        except (OSError, ObexError):
            pass

    def setpath(self, name="", up=False):
        """Enter child folder `name`; name="" goes to the root, up=True goes to the parent."""
        flags = 0x02 | (0x01 if up else 0)  # 0x02: don't create missing folders
        headers = [] if up else [(NAME, name)]
        code, _, _ = self._request(SETPATH, self._with_id(headers), struct.pack(">BB", flags, 0))
        self._check(code, "Opening folder %r" % name)

    def get(self, name=None, type_=None, params=b""):
        """Return (body bytes, application parameters bytes) of an object."""
        headers = []
        if name is not None:
            headers.append((NAME, name))
        if type_:
            headers.append((TYPE, type_))
        if params:
            headers.append((APP_PARAMS, params))
        headers = self._with_id(headers)
        body, reply_params = b"", b""
        while True:
            code, _, reply = self._request(GET | FINAL, headers)
            for hid, value in reply:
                if hid in (BODY, END_OF_BODY):
                    body += value
                elif hid == APP_PARAMS:
                    reply_params += value
            if code != CONTINUE:
                self._check(code, "Downloading")
                return body, reply_params
            headers = self._with_id([])  # later packets only ask for more

    def put(self, name, type_, data, params=b""):
        """Upload `data` (name=None sends no Name header); returns the reply headers."""
        headers = ([] if name is None else [(NAME, name)]) + [(TYPE, type_), (LENGTH, len(data))]
        if params:
            headers.append((APP_PARAMS, params))
        headers = self._with_id(headers)
        room = self.peer_max - 3 - sum(len(encode_header(h, v)) for h, v in headers) - 3
        offset = 0
        while True:
            chunk = data[offset:offset + max(room, 0)]
            offset += len(chunk)
            last = offset >= len(data)
            code, _, reply = self._request((PUT | FINAL) if last else PUT,
                                           headers + [(END_OF_BODY if last else BODY, chunk)])
            if last:
                self._check(code, "Sending")
                return reply
            if code != CONTINUE:
                self._check(code, "Sending")
            headers = []
            room = self.peer_max - 6
