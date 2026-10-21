import sqlite3

import pytest

from phonemessages.store import Store, conv_key

T = 1_790_000_000  # a fixed time so tests don't depend on the clock


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "messages.db"))
    yield s
    s.db.close()


# -- conv_key ------------------------------------------------------------

@pytest.mark.parametrize("a, b", [
    ("+1 (555) 123-4567", "5551234567"),
    ("+15551234567", "555-123-4567"),
    ("Jane@Example.com", "jane@example.com"),
])
def test_conv_key_groups_equivalent_addresses(a, b):
    assert conv_key(a) == conv_key(b)


@pytest.mark.parametrize("address, key", [
    ("+44 7700 900123", "7700900123"),  # last ten digits
    ("12345", "12345"),                 # short codes keep their digits
    ("Apple", "Apple"),                 # no digits: kept as written
    ("", ""),
    (None, ""),
])
def test_conv_key_values(address, key):
    assert conv_key(address) == key


# -- add -----------------------------------------------------------------

def test_add_returns_id_and_stores_fields(store):
    msg_id = store.add("+1 555 123 4567", "hi", outgoing=False, name="Jane", ts=T, handle="h1")
    m = store.get(msg_id)
    assert (m["conv"], m["address"], m["name"], m["outgoing"], m["text"], m["ts"], m["handle"]) == \
        ("5551234567", "+1 555 123 4567", "Jane", 0, "hi", T, "h1")


def test_incoming_is_unread_and_outgoing_is_read(store):
    incoming = store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1")
    outgoing = store.add("5551234567", "hey", outgoing=True, ts=T + 1)
    assert store.get(incoming)["read"] == 0
    assert store.get(outgoing)["read"] == 1


def test_add_without_ts_uses_now(store, monkeypatch):
    monkeypatch.setattr("phonemessages.store.time.time", lambda: T + 42)
    assert store.get(store.add("5551234567", "hi", outgoing=True))["ts"] == T + 42


def test_same_phone_message_reported_twice_is_stored_once(store):
    assert store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1") is not None
    assert store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1") is None
    assert len(store.messages("5551234567")) == 1


def test_our_own_sends_are_never_deduplicated(store):
    # no handle: messages typed in Lime, so two identical ones are both real
    a = store.add("5551234567", "ok", outgoing=True, ts=T)
    b = store.add("5551234567", "ok", outgoing=True, ts=T)
    assert a is not None and b is not None and a != b


def test_add_keeps_reply_and_reaction_fields(store):
    target = store.add("5551234567", "Dinner?", outgoing=False, ts=T, handle="h1")
    react = store.add("5551234567", "Loved “Dinner?”", outgoing=True, ts=T + 5,
                      status="sending", reply_to=target, reaction="❤️")
    m = store.get(react)
    assert (m["reply_to"], m["reaction"], m["status"]) == (target, "❤️", "sending")


def test_set_status(store):
    msg_id = store.add("5551234567", "hi", outgoing=True, ts=T, status="sending")
    store.set_status(msg_id, "sent")
    assert store.get(msg_id)["status"] == "sent"


def test_messages_are_in_time_order(store):
    store.add("5551234567", "second", outgoing=False, ts=T + 10, handle="h2")
    store.add("5551234567", "first", outgoing=False, ts=T, handle="h1")
    assert [m["text"] for m in store.messages("5551234567")] == ["first", "second"]


# -- conversations -------------------------------------------------------

def test_conversations_newest_first_with_last_message_and_unread(store):
    store.add("5551111111", "old chat", outgoing=False, name="Ann", ts=T, handle="a1")
    store.add("5552222222", "hello", outgoing=False, name="Bob", ts=T + 10, handle="b1")
    store.add("5552222222", "you there?", outgoing=False, name="Bob", ts=T + 20, handle="b2")
    store.add("5552222222", "yes", outgoing=True, ts=T + 30)
    convs = store.conversations()
    assert [c["conv"] for c in convs] == ["5552222222", "5551111111"]
    bob = convs[0]
    assert (bob["text"], bob["outgoing"], bob["name"], bob["unread"]) == ("yes", 1, "Bob", 2)


def test_conversation_name_prefers_contacts(store):
    store.add("5551234567", "hi", outgoing=False, name="Sender Name", ts=T, handle="h1")
    store.replace_contacts({"5551234567": ("Contact Name", None, "+15551234567")})
    assert store.conversations()[0]["name"] == "Contact Name"


def test_conversation_address_prefers_the_incoming_address(store):
    store.add("+1 555 123 4567", "hi", outgoing=False, ts=T, handle="h1")
    store.add("5551234567", "hey", outgoing=True, ts=T + 1)
    assert store.conversations()[0]["address"] == "+1 555 123 4567"


# -- mark_read -----------------------------------------------------------

def test_mark_read(store):
    store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1")
    store.add("5559999999", "other", outgoing=False, ts=T, handle="h2")
    assert store.mark_read("5551234567") is True
    assert store.mark_read("5551234567") is False  # nothing left to change
    unread = {c["conv"]: c["unread"] for c in store.conversations()}
    assert unread == {"5551234567": 0, "5559999999": 1}


# -- delete --------------------------------------------------------------

def test_delete_conversation_removes_only_that_chat(store):
    store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1")
    store.add("5551234567", "hey", outgoing=True, ts=T + 1)
    store.add("5559999999", "keep me", outgoing=False, ts=T, handle="h2")
    store.delete_conversation("5551234567")
    assert store.messages("5551234567") == []
    assert [c["conv"] for c in store.conversations()] == ["5559999999"]


def test_deleted_phone_messages_are_not_imported_again(store):
    store.add("5551234567", "hi", outgoing=False, ts=T, handle="h1")
    assert store.has_handle("h1", T)
    store.delete_conversation("5551234567")
    # the phone relists the message: MapClient asks has_handle() before fetching it
    assert store.has_handle("h1", T)
    assert store.has_handle("h1", T + 0.5)  # timestamps within a second still match
    assert not store.has_handle("h1", T + 5)
    assert not store.has_handle("other", T)


def test_deleting_our_own_sends_records_nothing(store):
    store.add("5551234567", "hey", outgoing=True, ts=T)
    store.delete_conversation("5551234567")
    assert store.db.execute("SELECT count(*) FROM deleted").fetchone()[0] == 0


def test_delete_message(store):
    keep = store.add("5551234567", "keep", outgoing=False, ts=T, handle="h1")
    drop = store.add("5551234567", "drop", outgoing=False, ts=T + 1, handle="h2")
    store.delete_message(drop)
    assert [m["id"] for m in store.messages("5551234567")] == [keep]
    assert store.has_handle("h2", T + 1)


# -- contacts ------------------------------------------------------------

def test_replace_contacts_and_lookups(store, tmp_path):
    photo = tmp_path / "jane.jpg"
    photo.write_bytes(b"jpeg")
    store.replace_contacts({"5551234567": ("Jane", str(photo), "+15551234567")})
    assert store.contact_name("+1 (555) 123-4567") == "Jane"
    assert store.contact_photo("5551234567") == str(photo)
    store.replace_contacts({"5559999999": ("Bob", str(tmp_path / "missing.jpg"), "5559999999")})
    assert store.contact_name("5551234567") == ""  # replaced, not merged
    assert store.contact_photo("5559999999") is None  # file doesn't exist
    assert [c["name"] for c in store.contacts()] == ["Bob"]


# -- migrations ----------------------------------------------------------

def test_opening_an_old_database_adds_columns_and_keeps_rows(tmp_path):
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY, conv TEXT NOT NULL, address TEXT NOT NULL, name TEXT,
        outgoing INTEGER NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL, handle TEXT,
        status TEXT, dedupe TEXT UNIQUE)""")
    db.execute("CREATE TABLE contacts (key TEXT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute("INSERT INTO messages (conv, address, name, outgoing, text, ts, handle) "
               "VALUES ('5551234567', '5551234567', 'Jane', 0, 'from an old version', ?, 'h1')", (T,))
    db.execute("INSERT INTO contacts VALUES ('5551234567', 'Jane')")
    db.commit()
    db.close()

    s = Store(path)
    [m] = s.messages("5551234567")
    assert m["text"] == "from an old version"
    assert m["read"] == 1  # existing messages count as read
    assert m["reply_to"] is None and m["reaction"] is None
    assert s.contacts()[0]["name"] == "Jane"
    assert s.contacts()[0]["photo"] is None
    s.db.close()
