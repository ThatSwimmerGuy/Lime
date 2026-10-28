import pytest

from phonemessages import edits
from phonemessages.store import Store

T = 1_790_000_000  # a fixed time so tests don't depend on the clock


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "messages.db"))
    yield s
    s.db.close()


def send(store, text, ts, **kw):
    return store.add("5551234567", text, outgoing=True, ts=ts, status=kw.pop("status", "sent"), **kw)


def shown(store):
    return edits.fold(store.messages("5551234567"))


def test_wire_text_marks_the_correction_with_an_asterisk():
    assert edits.wire_text("See you at 6") == "*See you at 6"


def test_store_keeps_edit_of(store):
    target = send(store, "See you at 5", T)
    edit = send(store, "See you at 6", T + 10, edit_of=target)
    assert store.get(edit)["edit_of"] == target


def test_message_without_edits_is_unchanged(store):
    send(store, "Hi", T)
    [m] = shown(store)
    assert (m["text"], m["versions"]) == ("Hi", [])


def test_edit_replaces_the_text_in_the_original_bubble(store):
    target = send(store, "See you at 5", T)
    send(store, "Thanks", T + 5)
    send(store, "See you at 6", T + 10, edit_of=target)
    msgs = shown(store)
    assert [m["text"] for m in msgs] == ["See you at 6", "Thanks"]
    assert msgs[0]["id"] == target
    assert msgs[0]["versions"] == ["See you at 5"]


def test_later_edits_win_and_earlier_versions_are_kept_in_order(store):
    target = send(store, "one", T)
    send(store, "two", T + 10, edit_of=target)
    send(store, "three", T + 20, edit_of=target)
    [m] = shown(store)
    assert (m["text"], m["versions"]) == ("three", ["one", "two"])


def test_failed_edit_is_not_applied(store):
    target = send(store, "See you at 5", T)
    send(store, "See you at 6", T + 10, edit_of=target, status="failed")
    [m] = shown(store)
    assert (m["text"], m["versions"]) == ("See you at 5", [])


def test_edit_whose_original_is_gone_is_hidden(store):
    target = send(store, "See you at 5", T)
    send(store, "See you at 6", T + 10, edit_of=target)
    store.delete_message(target)
    assert shown(store) == []
