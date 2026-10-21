# Changes, explained

One section per phase of work. Each one says what changed and, more importantly,
*why* the code works the way it does.

## Phase 0: Test harness

No app behaviour changed in this phase. It only adds tests.

### What was added

- `pytest.ini`: tells pytest to look in `tests/` and to put the repository root on the
  import path (`pythonpath = .`). That's what lets `from phonemessages import store` work in
  a test without installing Lime as a package.
- `tests/test_bmessage.py`, `tests/test_reactions.py`, `tests/test_store.py`: unit tests
  for the three modules with no GTK or Bluetooth code in them.
- `.github/workflows/tests.yml`: runs the tests on GitHub for every push and pull request,
  on Python 3.10 and 3.13.

### Why only these three modules

`bmessage.py`, `reactions.py` and `store.py` import nothing from GTK, D-Bus or BlueZ. They take
plain values in and give plain values back, so a test can call them directly. `app.py`,
`map_client.py` and `contacts.py` need a running D-Bus session, obexd and a real iPhone, so
they can't be tested this way yet. Later phases move logic out of those files so more of it
can be tested.

The CI machine therefore only needs `pytest`. It doesn't need GTK, PyGObject or BlueZ,
because none of the tested code imports them.

### How the store tests work

Each test gets a brand-new SQLite file from pytest's `tmp_path` fixture, a temporary folder
that's deleted afterwards. Tests never touch your real `messages.db`, and they can't affect
each other.

Messages get fixed timestamps (`T = 1_790_000_000`) instead of the current time, so a test
gives the same result whenever it runs. Where the code calls `time.time()` itself, the test
replaces that function with `monkeypatch` for the duration of that test.

`test_opening_an_old_database_adds_columns_and_keeps_rows` builds a database the way the very
first version of Lime did, without the `read`, `reply_to`, `reaction`, `photo` and `address`
columns. It then opens it with today's `Store`. This checks that the `ALTER TABLE` upgrades in
`Store.__init__` keep existing messages. Every later schema change will get a test like it.

### What the tests deliberately leave out

The duplicate-message bug (Phase 1) isn't tested here. A test of today's behaviour would
assert that a genuine second "ok" gets dropped, which locks the bug in. Phase 1 starts with a
test for the *correct* behaviour instead, and that test fails until the fix is in.

`parse_timestamp` with an offset written as `+02:00` (with a colon) isn't tested either.
Today that's read as local time and the offset is ignored. That may or may not matter, since
it's unclear iPhones ever send that form, so it's left alone rather than locked in.

### Dependencies

`pytest` is only needed to run the tests, not to run Lime. So it isn't added to the Flatpak
manifest, which describes what the *app* needs. It's listed in the README's new
"Development" section instead, with the package name for each distro.
