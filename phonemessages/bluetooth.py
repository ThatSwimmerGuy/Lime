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
PBAP_PSE = 0x112F  # Phonebook Server
BASE_UUID = "0000%04X-0000-1000-8000-00805F9B34FB"


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
