import pytest

from phonemessages.store import MAX_PINS, Store

T = 1_790_000_000  # a fixed time so tests don't depend on the clock


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "messages.db"))
    yield s
    s.db.close()


def test_nothing_pinned_at_first(store):
    assert store.pinned() == []


def test_pins_keep_the_order_they_were_pinned_in(store):
    for conv in ("5550000003", "5550000001", "5550000002"):
        store.pin(conv)
    assert store.pinned() == ["5550000003", "5550000001", "5550000002"]


def test_pinning_twice_keeps_one_pin_in_its_place(store):
    store.pin("5550000001")
    store.pin("5550000002")
    assert store.pin("5550000001")
    assert store.pinned() == ["5550000001", "5550000002"]


def test_unpin(store):
    store.pin("5550000001")
    store.pin("5550000002")
    store.unpin("5550000001")
    assert store.pinned() == ["5550000002"]


def test_unpinned_then_pinned_again_goes_last(store):
    store.pin("5550000001")
    store.pin("5550000002")
    store.unpin("5550000001")
    store.pin("5550000001")
    assert store.pinned() == ["5550000002", "5550000001"]


def test_at_most_nine_pins(store):
    for i in range(MAX_PINS):
        assert store.pin("55500000%02d" % i)
    assert not store.pin("5550000099")
    assert len(store.pinned()) == MAX_PINS
    assert "5550000099" not in store.pinned()


def test_deleting_a_conversation_unpins_it(store):
    store.add("5550000001", "Hi", outgoing=False, ts=T)
    store.pin("5550000001")
    store.delete_conversation("5550000001")
    assert store.pinned() == []


def test_pins_survive_reopening_the_database(tmp_path):
    path = str(tmp_path / "messages.db")
    s = Store(path)
    s.pin("5550000001")
    s.db.close()
    again = Store(path)
    assert again.pinned() == ["5550000001"]
    again.db.close()
