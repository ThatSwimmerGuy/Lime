from datetime import datetime, timedelta, timezone

import pytest

from phonemessages import bmessage

# Roughly what an iPhone hands back for an incoming text.
INCOMING = (
    "BEGIN:BMSG\r\n"
    "VERSION:1.0\r\n"
    "STATUS:UNREAD\r\n"
    "TYPE:SMS_GSM\r\n"
    "FOLDER:telecom/msg/inbox\r\n"
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Smith;John\r\nTEL;TYPE=CELL:+15551234567\r\nEND:VCARD\r\n"
    "BEGIN:BENV\r\n"
    "BEGIN:VCARD\r\nVERSION:2.1\r\nFN:Me\r\nTEL:+15559876543\r\nEND:VCARD\r\n"
    "BEGIN:BBODY\r\n"
    "CHARSET:UTF-8\r\n"
    "LENGTH:40\r\n"
    "BEGIN:MSG\r\nSee you at 6\r\nbring snacks 🍿\r\nEND:MSG\r\n"
    "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n"
).encode("utf-8")


# -- build ---------------------------------------------------------------

def test_build_returns_utf8_bytes_with_crlf_lines():
    data = bmessage.build("+15551234567", "hello")
    assert isinstance(data, bytes)
    text = data.decode("utf-8")
    assert text.startswith("BEGIN:BMSG\r\n")
    assert text.endswith("END:BMSG\r\n")
    assert "\n" not in text.replace("\r\n", "")  # no bare LF anywhere


def test_build_addresses_the_recipient_and_targets_the_outbox():
    text = bmessage.build("+15551234567", "hi", recipient_name="Alice").decode("utf-8")
    assert "FOLDER:telecom/msg/outbox\r\n" in text
    envelope = text.split("BEGIN:BENV")[1]
    assert "N:Alice\r\n" in envelope
    assert "TEL:+15551234567\r\n" in envelope


@pytest.mark.parametrize("body", ["hello", "line one\nline two", "naïve café 👋🏽", "a\r\nb"])
def test_build_length_counts_bytes_of_the_msg_block(body):
    text = bmessage.build("+1555", body).decode("utf-8")
    length = int(text.split("LENGTH:")[1].split("\r\n")[0])
    msg_block = text[text.index("BEGIN:MSG"):text.index("END:BBODY")]
    assert length == len(msg_block.encode("utf-8"))


def test_build_normalises_line_endings_in_the_body():
    text = bmessage.build("+1555", "one\ntwo\r\nthree").decode("utf-8")
    assert "BEGIN:MSG\r\none\r\ntwo\r\nthree\r\nEND:MSG\r\n" in text


# -- parse ---------------------------------------------------------------

def test_parse_incoming_message():
    parsed = bmessage.parse(INCOMING)
    assert parsed == {
        "folder": "telecom/msg/inbox",
        "sender_name": "John Smith",  # from N:Smith;John since there's no FN
        "sender_address": "+15551234567",  # TEL with parameters
        "recipient_name": "Me",
        "recipient_address": "+15559876543",
        "text": "See you at 6\nbring snacks 🍿",
    }


def test_parse_prefers_fn_over_n_and_falls_back_to_email():
    data = (
        "BEGIN:BMSG\nFOLDER:telecom/msg/inbox\n"
        "BEGIN:VCARD\nN:Doe;Jane\nFN:Janie\nEMAIL:jane@example.com\nEND:VCARD\n"
        "BEGIN:BENV\nBEGIN:BBODY\nBEGIN:MSG\nhey\nEND:MSG\nEND:BBODY\nEND:BENV\nEND:BMSG\n"
    ).encode()
    parsed = bmessage.parse(data)
    assert parsed["sender_name"] == "Janie"
    assert parsed["sender_address"] == "jane@example.com"


def test_parse_joins_multiple_msg_parts():
    data = (
        "BEGIN:BMSG\nBEGIN:BENV\nBEGIN:BBODY\n"
        "BEGIN:MSG\npart one\nEND:MSG\nBEGIN:MSG\npart two\nEND:MSG\n"
        "END:BBODY\nEND:BENV\nEND:BMSG\n"
    ).encode()
    assert bmessage.parse(data)["text"] == "part one\npart two"


@pytest.mark.parametrize("data", [b"", b"garbage", b"BEGIN:BMSG\r\nBEGIN:MSG\r\n", b"\xff\xfe\x00broken utf8"])
def test_parse_malformed_input_returns_empty_fields(data):
    parsed = bmessage.parse(data)
    assert parsed["folder"] == ""
    assert parsed["sender_address"] == ""
    assert parsed["recipient_address"] == ""
    assert parsed["text"] == ""


# -- round trip ----------------------------------------------------------

@pytest.mark.parametrize("body", [
    "ok",
    "first line\nsecond line\n\nfourth after a blank",
    "Ünïcödé, 中文 and emoji 👍❤️‼️",
    'reply:"How was your day?"\nGreat!',
])
def test_build_then_parse_round_trip(body):
    parsed = bmessage.parse(bmessage.build("+447700900123", body, recipient_name="Bob"))
    assert parsed["folder"] == "telecom/msg/outbox"
    assert parsed["recipient_name"] == "Bob"
    assert parsed["recipient_address"] == "+447700900123"
    assert parsed["sender_address"] == ""  # left blank for the phone to fill in
    assert parsed["text"] == body


# -- parse_timestamp -----------------------------------------------------

def test_timestamp_utc_z():
    expected = datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc).timestamp()
    assert bmessage.parse_timestamp("20261019T153000Z") == expected


@pytest.mark.parametrize("suffix, offset", [("+0200", 2), ("-0500", -5), ("+0000", 0)])
def test_timestamp_with_offset(suffix, offset):
    tz = timezone(timedelta(hours=offset))
    expected = datetime(2026, 10, 19, 15, 30, tzinfo=tz).timestamp()
    assert bmessage.parse_timestamp("20261019T153000" + suffix) == expected


def test_timestamp_without_zone_is_local_time():
    expected = datetime(2026, 10, 19, 15, 30).timestamp()  # naive = local
    assert bmessage.parse_timestamp("20261019T153000") == expected


@pytest.mark.parametrize("value", [None, "", "yesterday", "20261319T153000", "2026-10-19 15:30", "20261019"])
def test_timestamp_malformed_returns_none(value):
    assert bmessage.parse_timestamp(value) is None
