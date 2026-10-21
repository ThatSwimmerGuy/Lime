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

## Extra: Apple-style Settings and New Message

You asked for this between phases. Both windows save the same settings and do the same
things as before. The one addition is a Connect Automatically switch, which controls
behaviour Lime already had.

### Settings window

Settings used to be a popover hanging off the gear button. It's now its own window, like
the Settings window of a Mac app. The gear button and **Ctrl+,** (the Mac shortcut is ⌘,)
both open it, and there's only ever one: `open_settings()` brings the existing window to the
front instead of making a second.

- **Icon tabs in the toolbar.** General and Appearance are two `Gtk.RadioButton`s with
  `draw_indicator=False`, each holding an icon above a label. Because they share a group, only
  one can be selected. Selecting one switches a `Gtk.Stack` to that page and sets the window
  title to the tab's name, as macOS does. Icons are looked up by several names
  (`Gio.ThemedIcon.new_from_names`), so the first one the user's icon theme has is used.
- **The window resizes to fit each page.** The stack has `vhomogeneous=False`, so it doesn't
  reserve the tallest page's height for every page, and `interpolate_size=True` animates the
  change. The window isn't user-resizable, so GTK sizes it to its content.
- **The first tab is shown after `show_all()`.** A `Gtk.Stack` refuses to switch to a page
  that isn't visible yet, so selecting a page before the widgets are shown does nothing.
- **One config dictionary.** The Settings window uses the main window's `cfg` dict instead
  of loading its own copy. With two copies, whichever window saved last would overwrite the
  other's changes.
- **General tab (new):** shows the paired iPhone and a **Connect Automatically** switch. The
  switch sets the same `auto_connect` value that Connect and Disconnect already set, and the
  background reconnect timer already reads it. So it's a new control for existing behaviour,
  not a new feature. Pressing Connect or Disconnect while Settings is open can change that
  value, so the tab refreshes whenever the window comes back into focus.
- **Appearance tab:** bubble colours and window-button position, as before.
- **Grouped cards.** `settings_group()` builds a rounded box of rows, with a label on the left,
  a control on the right, and a hairline between rows. That's the layout of macOS Settings.
- **Round colour swatches.** A `Gtk.ColorButton` draws its colour in a child widget, a
  "colorswatch", which is wider than it is tall by default. The code forces it to 20×20, and
  CSS rounds both the swatch and its `overlay` layer. The theme draws the swatch's outline on
  that overlay, so with only the swatch rounded you got a circle inside a square.
- **Segmented Left/Right control,** built from radio buttons the same way as the tabs. Each
  `toggled` handler only acts when its button became *active*, because switching also fires
  `toggled` on the button that turned off.
- **macOS-style switch:** grey track, blue when on, round white knob. That's plain CSS on
  GTK's `switch` and `slider` nodes.

### New Message window

- **Header bar with Cancel and Start.** `use_header_bar=True` makes GTK put the dialog's
  buttons in the title bar: Cancel on the left, Start on the right. They reuse the existing
  `.capsule` style, and Start gets `.suggested`, which is the blue one.
- **A "To:" line like the Messages app.** It's a label and a borderless entry, with a hairline
  under it. It's still a `Gtk.SearchEntry`, because the contact filter listens for its
  `search-changed` signal. Only the magnifying-glass icon is removed.
- **Shorter instructions.** The long "To: pick a contact…" text became one small grey hint
  under the To: line. The information is the same.
- **Selected contact in blue,** as in macOS lists (`list.contacts row:selected`).

The CSS selector is `.new-message`, not `dialog.new-message`, so the dark background also
applies when the screenshot tool moves the dialog's contents into another window.

Phase 3 (GTK 4) will rebuild these windows, and should keep this look.
