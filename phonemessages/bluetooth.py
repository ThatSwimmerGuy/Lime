"""Bluetooth sockets without BlueZ's D-Bus services: list paired devices and open an RFCOMM
connection to a service on the phone by its UUID.

On Windows this goes through Winsock and the Bluetooth API (via ctypes), which look up
the service's channel themselves. On Linux it asks the phone's SDP server for the channel.
"""
import ctypes
import socket
import struct
import sys

MAP_MAS = 0x1132   # Message Access Server
MAP_MNS = 0x1133   # Message Notification Server (us, receiving new-message events)
MAP_PROFILE = 0x1134
PBAP_PCE = 0x112E  # Phonebook client (us)
PBAP_PSE = 0x112F  # Phonebook Server
PBAP_PROFILE = 0x1130
BASE_UUID = "0000%04X-0000-1000-8000-00805F9B34FB"


# -- SDP records -----------------------------------------------------------------
# The iPhone only offers "Show Notifications" and "Sync Contacts" for a computer whose
# SDP records say it's a MAP and PBAP client. BlueZ publishes these on Linux; on Windows
# Lime has to publish them itself.

def _seq(*items):
    body = b"".join(items)
    return (b"\x35" + bytes([len(body)]) if len(body) < 256 else b"\x36" + struct.pack(">H", len(body))) + body


def _uuid16(value):
    return b"\x19" + struct.pack(">H", value)


def _uint(value, size):
    return {1: b"\x08", 2: b"\x09", 4: b"\x0a"}[size] + value.to_bytes(size, "big")


def _text(value):
    data = value.encode("utf-8")
    return b"\x25" + bytes([len(data)]) + data


def _record(*attrs):
    return _seq(*(_uint(aid, 2) + value for aid, value in attrs))


def mns_record(channel):
    """MAP Message Notification Server on RFCOMM `channel` (modelled on BlueZ's)."""
    return _record(
        (0x0001, _seq(_uuid16(MAP_MNS))),
        (0x0004, _seq(_seq(_uuid16(0x0100)), _seq(_uuid16(0x0003), _uint(channel, 1)), _seq(_uuid16(0x0008)))),
        (0x0005, _seq(_uuid16(0x1002))),  # public browse group
        (0x0009, _seq(_seq(_uuid16(MAP_PROFILE), _uint(0x0102, 2)))),  # MAP 1.2
        (0x0100, _text("MAP MNS")),
        (0x0317, _uint(0x0000001F, 4)),  # supported MAP features
    )


def pce_record():
    """PBAP Phonebook Client; it has no channel, it only says we'd like contacts."""
    return _record(
        (0x0001, _seq(_uuid16(PBAP_PCE))),
        (0x0005, _seq(_uuid16(0x1002))),
        (0x0009, _seq(_seq(_uuid16(PBAP_PROFILE), _uint(0x0102, 2)))),  # PBAP 1.2
        (0x0100, _text("Phonebook Access PCE")),
    )


def _addr_to_int(address):
    return int(address.replace(":", ""), 16)


def _int_to_addr(value):
    return ":".join("%02X" % ((value >> (8 * i)) & 0xFF) for i in range(5, -1, -1))


# -- Windows -------------------------------------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        @classmethod
        def from_uuid16(cls, short):
            tail = bytes.fromhex("800000805F9B34FB")
            return cls(short, 0x0000, 0x1000, (ctypes.c_ubyte * 8)(*tail))

    class SOCKADDR_BTH(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("addressFamily", ctypes.c_ushort), ("btAddr", ctypes.c_ulonglong),
                    ("serviceClassId", GUID), ("port", ctypes.c_ulong)]

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [(n, wintypes.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay",
                                                 "wHour", "wMinute", "wSecond", "wMilliseconds")]

    class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("fReturnAuthenticated", wintypes.BOOL),
                    ("fReturnRemembered", wintypes.BOOL), ("fReturnUnknown", wintypes.BOOL),
                    ("fReturnConnected", wintypes.BOOL), ("fIssueInquiry", wintypes.BOOL),
                    ("cTimeoutMultiplier", ctypes.c_ubyte), ("hRadio", wintypes.HANDLE)]

    class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("Address", ctypes.c_ulonglong),
                    ("ulClassofDevice", wintypes.ULONG), ("fConnected", wintypes.BOOL),
                    ("fRemembered", wintypes.BOOL), ("fAuthenticated", wintypes.BOOL),
                    ("stLastSeen", SYSTEMTIME), ("stLastUsed", SYSTEMTIME),
                    ("szName", wintypes.WCHAR * 248)]

    def paired_devices():
        """[(address, name)] of paired Bluetooth devices, phones first."""
        for name in ("bthprops.cpl", "BluetoothApis.dll"):
            try:
                api = ctypes.WinDLL(name)
                break
            except OSError:
                continue
        else:
            return []
        api.BluetoothFindFirstDevice.restype = wintypes.HANDLE
        params = BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.sizeof(BLUETOOTH_DEVICE_SEARCH_PARAMS),
                                                True, True, False, True, False, 0, None)
        info = BLUETOOTH_DEVICE_INFO()
        info.dwSize = ctypes.sizeof(BLUETOOTH_DEVICE_INFO)
        handle = api.BluetoothFindFirstDevice(ctypes.byref(params), ctypes.byref(info))
        if not handle:
            return []
        devices = []
        try:
            while True:
                if info.fAuthenticated:
                    is_phone = (info.ulClassofDevice >> 8) & 0x1F == 0x02  # major class: phone
                    devices.append((not is_phone, info.szName or _int_to_addr(info.Address),
                                    _int_to_addr(info.Address)))
                if not api.BluetoothFindNextDevice(wintypes.HANDLE(handle), ctypes.byref(info)):
                    break
        finally:
            api.BluetoothFindDeviceClose(wintypes.HANDLE(handle))
        return [(addr, name) for _, name, addr in sorted(devices)]

    NS_BTH = 16
    BT_PORT_ANY = 0xFFFFFFFF
    RNRSERVICE_REGISTER = 0

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]

    class CSADDR_INFO(ctypes.Structure):
        _fields_ = [("LocalAddr", SOCKET_ADDRESS), ("RemoteAddr", SOCKET_ADDRESS),
                    ("iSocketType", ctypes.c_int), ("iProtocol", ctypes.c_int)]

    class BLOB(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.ULONG), ("pBlobData", ctypes.c_void_p)]

    class WSAQUERYSETW(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("lpszServiceInstanceName", wintypes.LPWSTR),
                    ("lpServiceClassId", ctypes.POINTER(GUID)), ("lpVersion", ctypes.c_void_p),
                    ("lpszComment", wintypes.LPWSTR), ("dwNameSpace", wintypes.DWORD),
                    ("lpNSProviderId", ctypes.c_void_p), ("lpszContext", wintypes.LPWSTR),
                    ("dwNumberOfProtocols", wintypes.DWORD), ("lpafpProtocols", ctypes.c_void_p),
                    ("lpszQueryString", wintypes.LPWSTR), ("dwNumberOfCsAddrs", wintypes.DWORD),
                    ("lpcsaBuffer", ctypes.POINTER(CSADDR_INFO)), ("dwOutputFlags", wintypes.DWORD),
                    ("lpBlob", ctypes.POINTER(BLOB))]

    def _bth_set_service(record):
        """A BTH_SET_SERVICE blob: SDP version, record handle, then the raw record."""
        class BTH_SET_SERVICE(ctypes.Structure):
            _fields_ = [("pSdpVersion", ctypes.POINTER(wintypes.ULONG)),
                        ("pRecordHandle", ctypes.POINTER(wintypes.HANDLE)),
                        ("fCodService", wintypes.ULONG), ("Reserved", wintypes.ULONG * 5),
                        ("ulRecordLength", wintypes.ULONG), ("pRecord", ctypes.c_ubyte * len(record))]
        version, handle = wintypes.ULONG(1), wintypes.HANDLE()
        blob = BTH_SET_SERVICE(ctypes.pointer(version), ctypes.pointer(handle), 0, (wintypes.ULONG * 5)(),
                               len(record), (ctypes.c_ubyte * len(record))(*record))
        blob._keep = (version, handle)
        return blob

    def _register(name, service, record, sockaddr):
        ws2 = ctypes.WinDLL("ws2_32")
        guid = GUID.from_uuid16(service)
        csaddr = CSADDR_INFO(SOCKET_ADDRESS(ctypes.cast(ctypes.pointer(sockaddr), ctypes.c_void_p),
                                            ctypes.sizeof(sockaddr)),
                             SOCKET_ADDRESS(None, 0), socket.SOCK_STREAM, 3)
        payload = _bth_set_service(record)
        blob = BLOB(ctypes.sizeof(payload), ctypes.cast(ctypes.pointer(payload), ctypes.c_void_p))
        query = WSAQUERYSETW(ctypes.sizeof(WSAQUERYSETW), name, ctypes.pointer(guid), None, None, NS_BTH,
                             None, None, 0, None, None, 1, ctypes.pointer(csaddr), 0, ctypes.pointer(blob))
        if ws2.WSASetServiceW(ctypes.byref(query), RNRSERVICE_REGISTER, 0) != 0:
            code = ws2.WSAGetLastError()
            raise OSError(code, ctypes.FormatError(code).strip())

    def advertise():
        """Publish Lime's MAP notification server and PBAP client records. Returns the
        listening RFCOMM socket the iPhone sends new-message events to; the records stay
        published while Lime runs."""
        ws2 = ctypes.WinDLL("ws2_32")
        family = getattr(socket, "AF_BLUETOOTH", 32)
        server = socket.socket(family, socket.SOCK_STREAM, getattr(socket, "BTPROTO_RFCOMM", 3))
        addr = SOCKADDR_BTH(family, 0, GUID(), BT_PORT_ANY)
        fd = ctypes.c_size_t(server.fileno())
        size = ctypes.c_int(ctypes.sizeof(addr))
        if (ws2.bind(fd, ctypes.byref(addr), ctypes.sizeof(addr)) != 0 or ws2.listen(fd, 2) != 0
                or ws2.getsockname(fd, ctypes.byref(addr), ctypes.byref(size)) != 0):
            code = ws2.WSAGetLastError()
            server.close()
            raise OSError(code, ctypes.FormatError(code).strip())
        _register("MAP MNS", MAP_MNS, mns_record(addr.port), addr)
        try:
            _register("Phonebook Access PCE", PBAP_PCE, pce_record(), addr)
        except OSError:
            pass  # contacts are a nice extra; messages matter more
        return server

    def accept(server):
        """Wait for the phone to connect to `server`; returns the connected socket."""
        ws2 = ctypes.WinDLL("ws2_32")
        ws2.accept.restype = ctypes.c_size_t
        handle = ws2.accept(ctypes.c_size_t(server.fileno()), None, None)
        if handle == ctypes.c_size_t(-1).value:  # INVALID_SOCKET
            code = ws2.WSAGetLastError()
            raise OSError(code, ctypes.FormatError(code).strip())
        sock = socket.socket(server.family, socket.SOCK_STREAM, server.proto, fileno=handle)
        sock.settimeout(120)
        return sock

    def connect(address, service, timeout=30):
        """A connected RFCOMM socket to `service` (a 16-bit UUID) on the device."""
        # some Python builds (MSYS2's) leave out the constants, but Winsock still has them
        family = getattr(socket, "AF_BLUETOOTH", 32)
        sock = socket.socket(family, socket.SOCK_STREAM, getattr(socket, "BTPROTO_RFCOMM", 3))
        # Python only connects to a channel number; Winsock can take the service UUID
        # instead (port 0) and run the SDP query itself.
        addr = SOCKADDR_BTH(family, _addr_to_int(address), GUID.from_uuid16(service), 0)
        ws2 = ctypes.WinDLL("ws2_32")
        if ws2.connect(ctypes.c_size_t(sock.fileno()), ctypes.byref(addr), ctypes.sizeof(addr)) != 0:
            code = ws2.WSAGetLastError()
            sock.close()
            raise OSError(code, ctypes.FormatError(code).strip())
        sock.settimeout(timeout)
        return sock


# -- Linux ---------------------------------------------------------------------

else:
    def advertise():
        return None  # BlueZ already publishes these records on Linux

    def accept(server):
        raise OSError("Not supported")

    def paired_devices():
        from .map_client import paired_devices as bluez_paired
        return bluez_paired()

    def _data_element(data, i):
        """Parse one SDP data element at data[i]; returns (value, next index)."""
        head = data[i]
        kind, size_index = head >> 3, head & 0x07
        i += 1
        if kind == 0:
            return None, i
        if size_index < 5:
            size = 1 << size_index
        else:
            width = 1 << (size_index - 5)
            size = int.from_bytes(data[i:i + width], "big")
            i += width
        raw = data[i:i + size]
        end = i + size
        if kind in (6, 7):  # sequence / alternative
            items, j = [], i
            while j < end:
                item, j = _data_element(data, j)
                items.append(item)
            return items, end
        if kind in (1, 2, 3, 5):  # integers, UUIDs (16/32-bit as ints) and booleans
            return int.from_bytes(raw, "big"), end
        return raw, end

    def rfcomm_channel(address, service, timeout=15):
        """Ask the device's SDP server which RFCOMM channel `service` listens on."""
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        sock.settimeout(timeout)
        try:
            sock.connect((address, 1))  # PSM 1 is SDP
            pattern = bytes([0x35, 0x03, 0x19]) + struct.pack(">H", service)
            attrs = bytes([0x35, 0x03, 0x09, 0x00, 0x04])  # ProtocolDescriptorList
            result, cont, tid = b"", b"\x00", 1
            while True:
                params = pattern + struct.pack(">H", 0xFFFF) + attrs + cont
                sock.send(struct.pack(">BHH", 0x06, tid, len(params)) + params)
                reply = sock.recv(4096)
                if not reply or reply[0] != 0x07:
                    raise OSError("The phone's service lookup failed.")
                (count,) = struct.unpack_from(">H", reply, 5)
                result += reply[7:7 + count]
                cont = reply[7 + count:]
                if not cont or cont[0] == 0:
                    break
                tid += 1
        finally:
            sock.close()
        records, _ = _data_element(result, 0) if result else ([], 0)
        for record in records or []:
            values = dict(zip(record[::2], record[1::2]))
            for proto in values.get(0x0004) or []:
                if isinstance(proto, list) and proto[0] == 0x0003 and len(proto) > 1:
                    return proto[1]
        raise OSError("The iPhone doesn't offer this service. Is 'Show Notifications' on?")

    def connect(address, service, timeout=30):
        channel = rfcomm_channel(address, service)
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(timeout)
        try:
            sock.connect((address, channel))
        except OSError:
            sock.close()
            raise
        return sock
