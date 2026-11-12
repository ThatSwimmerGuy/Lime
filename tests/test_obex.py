import struct
import sys
import uuid

import pytest

from phonemessages import obex

MAP_TARGET = "bb582b40-420c-11db-b0de-0800200c9a66"


class FakePhone:
    """A socket that records what was sent and plays back scripted OBEX replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []
        self.inbox = b""

    def sendall(self, data):
        self.sent.append(data)
        if self.replies:
            reply = self.replies.pop(0)
            self.inbox += reply(data) if callable(reply) else reply

    def recv(self, n):
        data, self.inbox = self.inbox[:n], self.inbox[n:]
        return data


def packet(code, *headers, prefix=b""):
    body = b"".join(obex.encode_header(h, v) for h, v in headers)
    return struct.pack(">BH", code, 3 + len(prefix) + len(body)) + prefix + body


def connected(*replies, peer_max=0x2000):
    welcome = packet(obex.SUCCESS, (obex.CONNECTION_ID, 7), prefix=struct.pack(">BBH", 0x10, 0, peer_max))
    phone = FakePhone(welcome, *replies)
    client = obex.Client(phone)
    client.connect(MAP_TARGET)
    return client, phone


# -- headers ---------------------------------------------------------------

def test_text_headers_are_null_terminated_utf16():
    assert obex.encode_header(obex.NAME, "inbox") == b"\x01\x00\x0f" + "inbox\0".encode("utf-16-be")


def test_empty_name_is_just_the_header():
    assert obex.encode_header(obex.NAME, "") == b"\x01\x00\x03"


def test_type_headers_are_null_terminated_ascii():
    assert obex.encode_header(obex.TYPE, "x-bt/message") == b"\x42\x00\x10x-bt/message\0"


def test_headers_round_trip():
    headers = [(obex.NAME, "telecom"), (obex.BODY, b"\x00\x01"), (obex.CONNECTION_ID, 0xDEADBEEF),
               (0x97, 5)]
    data = b"".join(obex.encode_header(h, v) for h, v in headers)
    assert obex.decode_headers(data) == headers


def test_malformed_length_raises():
    with pytest.raises(obex.ObexError):
        obex.decode_headers(b"\x48\x00\x01")


def test_app_params_are_tag_length_value():
    assert obex.app_params((0x01, "H", 500), (0x13, "B", 255)) == b"\x01\x02\x01\xf4\x13\x01\xff"


# -- operations --------------------------------------------------------------

def test_connect_sends_target_and_keeps_connection_id_and_packet_size():
    client, phone = connected()
    opcode, size = struct.unpack_from(">BH", phone.sent[0])
    assert opcode == obex.CONNECT and size == len(phone.sent[0])
    assert uuid.UUID(MAP_TARGET).bytes in phone.sent[0]
    assert client.connection_id == 7
    assert client.peer_max == 0x2000


def test_connect_refused_raises_with_reason():
    phone = FakePhone(packet(0xC1, prefix=struct.pack(">BBH", 0x10, 0, 255)))
    with pytest.raises(obex.ObexError, match="Not Authorized"):
        obex.Client(phone).connect(MAP_TARGET)


def test_get_follows_continue_replies_and_joins_the_body():
    client, phone = connected(
        packet(obex.CONTINUE, (obex.BODY, b"<MAP-msg-")),
        packet(obex.SUCCESS, (obex.END_OF_BODY, b"listing/>"), (obex.APP_PARAMS, b"\x0d\x01\x01")),
    )
    body, params = client.get("inbox", "x-bt/MAP-msg-listing")
    assert body == b"<MAP-msg-listing/>"
    assert params == b"\x0d\x01\x01"
    first, second = phone.sent[1], phone.sent[2]
    assert first[0] == obex.GET | obex.FINAL
    assert obex.decode_headers(first[3:])[0] == (obex.CONNECTION_ID, 7)
    assert "inbox\0".encode("utf-16-be") in first
    assert obex.decode_headers(second[3:]) == [(obex.CONNECTION_ID, 7)]  # just asks for more


def test_get_not_found_raises():
    client, _ = connected(packet(0xC4))
    with pytest.raises(obex.ObexError, match="Not found"):
        client.get("nope")


def test_setpath_root_sends_empty_name_and_no_create_flag():
    client, phone = connected(packet(obex.SUCCESS))
    client.setpath("")
    sent = phone.sent[1]
    assert sent[0] == obex.SETPATH
    assert sent[3:5] == b"\x02\x00"
    assert obex.decode_headers(sent[5:]) == [(obex.CONNECTION_ID, 7), (obex.NAME, "")]


def test_put_splits_the_body_to_fit_the_phones_packet_size():
    data = bytes(range(256)) * 4
    def answer(sent):  # what a phone says to each PUT packet
        return packet(obex.SUCCESS if sent[0] & obex.FINAL else obex.CONTINUE)
    client, phone = connected(*[answer] * 10, peer_max=300)
    client.put("outbox", "x-bt/message", data, obex.app_params((0x14, "B", 1)))
    puts = phone.sent[1:]
    assert len(puts) > 3
    assert all(len(p) <= 300 for p in puts)
    assert [p[0] for p in puts[:-1]] == [obex.PUT] * (len(puts) - 1)
    assert puts[-1][0] == obex.PUT | obex.FINAL
    chunks = [v for p in puts for h, v in obex.decode_headers(p[3:]) if h in (obex.BODY, obex.END_OF_BODY)]
    assert b"".join(chunks) == data
    assert obex.decode_headers(puts[-1][3:])[-1][0] == obex.END_OF_BODY
    first = dict(obex.decode_headers(puts[0][3:]))
    assert first[obex.LENGTH] == len(data) and first[obex.NAME] == "outbox"


def test_put_rejected_raises():
    client, _ = connected(packet(0xC3))
    with pytest.raises(obex.ObexError, match="Forbidden"):
        client.put("outbox", "x-bt/message", b"hi")


def test_disconnect_from_the_phone_mid_reply_raises_connection_error():
    client, phone = connected(b"\xa0\x00")  # cut off after two bytes
    with pytest.raises(ConnectionError):
        client.get("inbox")


# -- SDP (finding the RFCOMM channel on Linux) ---------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="Windows looks up channels itself")
def test_sdp_protocol_descriptor_list_parses():
    from phonemessages.bluetooth import _data_element
    # one record: {0x0004: [[L2CAP], [RFCOMM, channel 2], [OBEX]]}
    l2cap = b"\x35\x03\x19\x01\x00"
    rfcomm = b"\x35\x05\x19\x00\x03\x08\x02"
    obex_ = b"\x35\x03\x19\x00\x08"
    protos = l2cap + rfcomm + obex_
    record = b"\x09\x00\x04\x35" + bytes([len(protos)]) + protos
    lists = b"\x35" + bytes([len(record) + 2]) + b"\x35" + bytes([len(record)]) + record
    value, end = _data_element(lists, 0)
    assert end == len(lists)
    assert value == [[0x0004, [[0x0100], [0x0003, 2], [0x0008]]]]


# -- MAP message listings ------------------------------------------------------

LISTING = b"""<?xml version="1.0"?>
<MAP-msg-listing version="1.0">
  <msg handle="1A2B" subject="See you at 6" datetime="20261112T143000" sender_name="John"
       sender_addressing="+15551234567" recipient_addressing="" type="SMS_GSM" sent="no"/>
  <msg handle="1A2C" subject="ok" datetime="20261112T143100" recipient_name="John"
       recipient_addressing="+15551234567" type="SMS_GSM" sent="yes"/>
</MAP-msg-listing>\0"""


def test_listing_gives_obexd_style_handles_and_properties():
    native = pytest.importorskip("phonemessages.native_client")  # needs PyGObject
    (h1, p1), (h2, p2) = native.parse_listing(LISTING, "inbox")
    assert h1 == "message%d" % 0x1A2B and h2 == "message%d" % 0x1A2C  # as obexd names them
    assert p1["Handle"] == "1A2B"
    assert p1["SenderAddress"] == "+15551234567" and p1["Timestamp"] == "20261112T143000"
    assert p1["Folder"] == "/telecom/msg/inbox" and not p1["Sent"]
    assert p2["Sent"]


def test_garbled_listing_is_empty():
    native = pytest.importorskip("phonemessages.native_client")
    assert native.parse_listing(b"<not xml", "inbox") == []


# -- what Lime publishes so the iPhone offers Show Notifications / Sync Contacts --------

@pytest.mark.skipif(sys.platform == "win32", reason="the SDP parser is the Linux code path")
def test_mns_record_says_map_notification_server_on_our_channel():
    from phonemessages import bluetooth
    record, end = bluetooth._data_element(bluetooth.mns_record(7), 0)
    assert end == len(bluetooth.mns_record(7))
    attrs = dict(zip(record[::2], record[1::2]))
    assert attrs[0x0001] == [bluetooth.MAP_MNS]
    assert [0x0003, 7] in attrs[0x0004]  # RFCOMM channel 7
    assert attrs[0x0009] == [[bluetooth.MAP_PROFILE, 0x0102]]


@pytest.mark.skipif(sys.platform == "win32", reason="the SDP parser is the Linux code path")
def test_pce_record_says_phonebook_client():
    from phonemessages import bluetooth
    record, _ = bluetooth._data_element(bluetooth.pce_record(), 0)
    attrs = dict(zip(record[::2], record[1::2]))
    assert attrs[0x0001] == [bluetooth.PBAP_PCE]
    assert attrs[0x0009] == [[bluetooth.PBAP_PROFILE, 0x0102]]


# -- the notification server (the phone is the client) --------------------------------

class ScriptedClient:
    """The phone's side of a notification connection: feeds packets, collects replies."""

    def __init__(self, *packets):
        self.inbox = b"".join(packets)
        self.sent = b""

    def recv(self, n):
        data, self.inbox = self.inbox[:n], self.inbox[n:]
        return data

    def sendall(self, data):
        self.sent += data

    def replies(self):
        out, data = [], self.sent
        while data:
            code, size = struct.unpack_from(">BH", data)
            out.append((code, data[3:size]))
            data = data[size:]
        return out


MNS_TARGET = uuid.UUID("bb582b41-420c-11db-b0de-0800200c9a66").bytes


def test_server_accepts_connect_and_collects_event_reports_across_packets():
    events = []
    phone = ScriptedClient(
        packet(obex.CONNECT, (obex.TARGET, MNS_TARGET), prefix=struct.pack(">BBH", 0x10, 0, 0x400)),
        packet(obex.PUT, (obex.CONNECTION_ID, 1), (obex.TYPE, "x-bt/MAP-event-report"),
               (obex.BODY, b"<MAP-event-report>")),
        packet(obex.PUT | obex.FINAL, (obex.END_OF_BODY, b"</MAP-event-report>")),
        packet(obex.DISCONNECT),
    )
    obex.serve(phone, lambda t, b: events.append((t, b)))
    replies = phone.replies()
    assert [code for code, _ in replies] == [obex.SUCCESS, obex.CONTINUE, obex.SUCCESS, obex.SUCCESS]
    connect_headers = dict(obex.decode_headers(replies[0][1][4:]))
    assert connect_headers[obex.WHO] == MNS_TARGET and obex.CONNECTION_ID in connect_headers
    assert events == [("x-bt/MAP-event-report", b"<MAP-event-report></MAP-event-report>")]


def test_server_stops_quietly_when_the_phone_goes_away():
    obex.serve(ScriptedClient(packet(obex.CONNECT, prefix=struct.pack(">BBH", 0x10, 0, 0x400))),
               lambda t, b: None)


def test_server_refuses_what_it_doesnt_do():
    phone = ScriptedClient(packet(obex.GET | obex.FINAL), packet(obex.DISCONNECT))
    obex.serve(phone, lambda t, b: None)
    assert [code for code, _ in phone.replies()] == [0xD1, obex.SUCCESS]


def test_put_without_name_sends_no_name_header():
    client, phone = connected(packet(obex.SUCCESS))
    client.put(None, "x-bt/MAP-NotificationRegistration", b"0", obex.app_params((0x0E, "B", 1)))
    hids = [h for h, _ in obex.decode_headers(phone.sent[1][3:])]
    assert obex.NAME not in hids and obex.TYPE in hids
