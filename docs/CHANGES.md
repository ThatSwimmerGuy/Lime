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

## Extra: Autocorrect and spell check

Also added between phases, at your request. New file: `phonemessages/spelling.py`, with tests
in `tests/test_spelling.py`.

### What it does

- **Autocorrect.** When you finish a word with a space, punctuation or Enter, a misspelled
  word is replaced with the dictionary's best close suggestion, for example `teh` → `the` and
  `recieve` → `receive`.
- **Undo with Backspace.** Pressing Backspace straight after a correction puts back what you
  typed. That word is then left alone for the rest of the session.
- **Red underline** under misspelled words, but only once you've moved past them. The word
  you're still typing isn't flagged.
- **Right-click menu** on an underlined word: up to five suggestions, **Learn Spelling**
  (adds the word to your personal dictionary for good) and **Ignore Spelling** (this session only).
- **Settings → General → Typing** has a switch for each feature. Both are on by default, as
  on a Mac.

### Why Enchant, through ctypes

The usual GTK add-on for this, gspell, isn't in the GNOME Flatpak runtime, so it would have to
be built into the Flatpak. Enchant, the engine underneath gspell, *is* in the runtime, along with
Hunspell dictionaries for many languages. `Speller` loads `libenchant-2.so.2` with Python's
built-in `ctypes` and calls its C functions directly: `enchant_dict_check`, `enchant_dict_suggest`
and `enchant_dict_add`. That means no new Python package and no new Flatpak module. From source,
it's one package for Enchant plus one dictionary.

If Enchant or a dictionary is missing, `Speller.load()` returns `None`, every spelling
method returns early, and the Typing switches are greyed out with a note. Lime works exactly
as before.

The dictionary comes from your locale: `LANG=en_GB.UTF-8` tries `en_GB`, then `en`, then
`en_US`.

### How a correction is chosen (`correction()`)

These rules are what make it feel like a Mac rather than a pushy spell checker:

1. **Leave alone:** all-caps words (NASA, LOL), capitalised words in the middle of a sentence
   (probably names), anything inside a link or email address, words you undid or ignored, and
   words of one or two letters.
2. **Chat shorthand first.** A small table fixes `i` → `I`, `im` → `I'm`, `dont` → `don't` and
   so on. The dictionary alone gets these wrong: Hunspell's first guess for `dont` is "font".
   `id` and `ill` are real words, so they're in the table as "leave alone".
3. **Only close suggestions.** Of the dictionary's top three suggestions, the first one within
   a small *edit distance* is used. That's at most 1 change for words of up to four letters,
   and 2 for longer words. Edit distance counts the inserts, deletes, substitutions and swaps
   of neighbouring letters needed to turn one word into the other (`teh` → `the` is one swap).
   Without this limit, a nonsense word would be "corrected" to something unrelated.
4. **Keep the capital:** `Teh` at the start of a sentence becomes `The`.

### How it hooks into the text box

- **When to correct:** the entry's text buffer emits `inserted-text` after every change. If
  the inserted text is a single space or punctuation mark, Lime schedules a correction with
  `GLib.idle_add`. Waiting until GTK is idle matters: changing the text *during* an insertion
  confuses GTK, and the cursor only moves past the space afterwards.
  (`inserted-text` is used rather than the entry's `insert-text` signal, because `insert-text`
  passes the position as a C pointer that Python can't read cleanly. GLib printed a warning on
  every keystroke.)
- **Keeping the cursor in place:** after replacing the word, the cursor moves by the
  difference in length between the old and new word.
- **Undo:** `last_fix` remembers the correction. Backspace only undoes it if the cursor is
  still right after the correction and its space. Any other typing clears `last_fix`.
- **Underlines:** `update_spelling()` runs on every change and cursor move, and gives the
  entry a Pango attribute list with an "error" underline in red for each misspelled word.
  Pango positions are *byte* offsets in UTF-8, not character positions. That's why the code
  converts with `len(text[:i].encode())`. Without the conversion, underlines would land in
  the wrong place after any emoji or accented letter.
- **Right-click:** GTK doesn't say which character was right-clicked, so `on_entry_button`
  works it out. It converts the click to the entry's coordinates, subtracts where the text
  layout starts (which accounts for scrolling), and asks Pango which character is there.

### Testing

`tests/test_spelling.py` tests all the decision logic against a small fake dictionary, so
it runs anywhere. I also checked the ctypes binding against real Enchant and the real compose
box inside the GNOME 51 Flatpak runtime: typing, autocorrect, Backspace undo, underlines, the
right-click menu, Enter-to-send and the Settings switches. And I checked that Lime still runs
normally without Enchant. Not yet tried: your real Lime with Enchant installed.

## Extra: Editing sent messages

Right-click one of your own messages and choose **Edit**. The compose box fills with the
message's text, under an "Editing message" bar (the same bar replies use). Change it and press
Enter, or press Esc to cancel.

### Why the edit goes out as `*corrected text`

Bluetooth MAP can only push *new* messages to the iPhone. There's no way to change one that
was already sent, so a real iMessage edit isn't possible. Instead Lime sends the corrected text
as a new message starting with an asterisk, which is how people already fix typos by text.
The other person sees two messages; you see one.

Edits other people make on their iPhone don't come through: the iPhone doesn't pass them
over Bluetooth.

### How it's stored and shown

- The edit is saved as its own row in `messages`, with a new `edit_of` column holding the
  id of the message it corrects. The row's text is the corrected text *without* the asterisk.
  Older databases get the column added when Lime starts, like `reply_to` and `reaction` were.
- `edits.fold()` runs before the reactions are folded in. It hides edit rows and puts the
  newest text into the original message, keeping the earlier texts in `versions`, oldest
  first. The bubble therefore stays where the original was in the conversation.
- Editing a message that was already edited still points at the *original* message, so a
  message can be edited any number of times and all versions are kept.
- An edit that fails to send isn't applied. The "Message not sent" bar explains why, just
  as for a failed reaction.
- A bubble with versions gets a small blue **Edited** button under it. Clicking it reveals
  the earlier versions above the bubble, like on iOS. Lime remembers which ones are open
  until it's restarted, so new messages arriving don't fold them shut again.
- **Edit** only appears for messages you sent that have finished sending. Messages with an
  attachment are left out, because their text is the iPhone's "Attachment: 1 Image" line.
- Sending the text unchanged just leaves edit mode without sending anything.

### Testing

`tests/test_edits.py` checks the asterisk, the new column, and the folding: one edit,
several edits, a failed edit, and an edit whose original was deleted. I also rendered the
real window with demo data, with an edited message open and the edit bar showing.

`tools/screenshots.py` had stopped working when autocorrect was added, because its stand-in
app had no `speller`. It now sets `app.speller = None`.

## Extra: Message box wraps instead of scrolling

A long message used to scroll sideways in a one-line box, so you couldn't see what you'd
written. The box now wraps onto new lines and grows as you type, like in Messages, up to
about six lines. After that it scrolls up and down.

### How it works

- The box is now a `Gtk.TextView` (the `ComposeView` class in `app.py`). A `Gtk.Entry` can
  only ever be one line.
- `ComposeView` has the same `get_text`, `set_text`, `get_position`, `set_position`,
  `insert_text` and `delete_text` methods as the old entry, so the send, reply, edit and
  autocorrect code didn't need to change.
- **Enter** still sends. **Shift+Enter** starts a new line. A new line also counts as the
  end of a word, so it triggers autocorrect (`"\n"` was added to `spelling.BOUNDARY`).
- The red spelling underline is now a text tag on the buffer, not a Pango attribute
  list. The right-clicked word for suggestions is found with `get_iter_at_location`.
- A text view has no placeholder, so "iMessage" is a grey label laid over the box. It's
  hidden while there's text, and clicks pass through it.
- The box sits in a `ScrolledWindow` with `propagate_natural_height` and
  `max_content_height=130`, which is what makes it grow and then stop growing. A CSS rule
  sets the scrollbar's minimum height to 0. Without it, the empty box was taller than one line.
- The send button now sits at the bottom of the box, like on a Mac.

### Testing

I rendered the real window with demo data three ways: with the box empty, with a
three-line message, and with a message too long for the box.

## Extra: Link previews

A message with a link in it now shows a card with the page's picture, title and site, like on
the iPhone. A Google Maps link shows a map of the place and its name. If the message is
*only* a link, the card replaces the text bubble, as in Messages. Click the card to open the
link in your browser; right-click it for React, Reply, Edit, Open Link and Copy Link.

New file: `phonemessages/links.py`, with tests in `tests/test_links.py`.

### Where the preview comes from

The iPhone doesn't send previews over Bluetooth, so Lime makes its own the way the iPhone
does: it downloads the page and reads the tags sites put there for previews, `og:title` and
`og:image` (Open Graph), with `twitter:*` and the page's `<title>` as fallbacks. Only the
`<head>` is read, at most 2 MB of it, and pictures over 8 MB are skipped.

- **User-Agent.** Some sites only include these tags for link-preview fetchers, and a plain
  browser gets a page built by JavaScript with no tags in it. So Lime identifies itself the
  way Apple's and Facebook's fetchers do (`facebookexternalhit`, `Twitterbot`).
- **Google Maps.** Google's title is always just "Google Maps", so the place name is taken
  from the link itself: `/maps/place/Space+Needle/@…` or `?q=Space+Needle`. Short links like
  `maps.app.goo.gl/…` work because the name is read from the address they redirect to. When
  Google doesn't know the location, its picture is a map of the ocean at 0,0, so that
  picture is dropped.
- **Links without `https://`**, like `www.example.com`, are found too. Punctuation at the end
  of a sentence isn't counted as part of the link, but a closing bracket that matches one in
  the link is, as in Wikipedia's `Lime_(fruit)`.

### Caching and background downloads

Each preview is saved in `~/.cache/phone-messages/link-previews/`, as a `.json` file and the
picture, both named by a hash of the link. So a link is downloaded once, not every time the
chat is redrawn. A link that has no preview, or that failed to load, is remembered too and tried
again after a day.

Downloads run on a pool of four background threads (`ThreadPoolExecutor`), so the window
never freezes waiting for a website. GTK may only be used from the main thread, so when a
download finishes, the thread hands back to it with `GLib.idle_add`, which redraws the chat.
`reload_messages(keep_scroll=True)` only scrolls to the bottom if you were already there,
so a preview loading doesn't yank you away from older messages you're reading.

### The card

The picture is drawn the same way as contact photos in `avatar()`: as a CSS background
with `background-size: cover`, because GTK 3 clips backgrounds to rounded corners but not
child widgets. The card is 260 pixels wide, and its height follows the picture's shape,
between 90 pixels and square. `GdkPixbuf.Pixbuf.get_file_info` checks that GTK can actually
show the picture format, and reads its size without loading the whole image.

### Privacy

Downloading a link tells that website your IP address. That's fine for links you send. But
a stranger could text you a link to their own server to find out where you are and that you
read their message. So links you *receive* are only previewed when they come from someone in
your contacts. **Settings → General → Links → Show Link Previews** turns previews off
altogether. The README's privacy line now says that link previews are the one time Lime goes
online.

### Flatpak

The Flatpak had no network access before, so `--share=network` is added to its
`finish-args`. Flathub reviewers ask about new permissions, and the answer is "link
previews". The manifest in your Flathub fork (`~/flathub-fork`) needs the same line.

### Testing

`tests/test_links.py` finds links in text, reads tags from sample pages, handles Google Maps
links, and checks the cache. It uses a fake internet (`FakeWeb`), so it runs offline.
I also fetched real previews for a Google Maps place, a Google Maps search, YouTube and
Wikipedia, and rendered the real window with a Google Maps link in the demo chat.
`tools/screenshots.py` now includes that link, so taking screenshots needs the internet.

## Extra: Pinned conversations

Right-click a conversation in the sidebar and choose **Pin**. It moves to a grid at the top of
the sidebar as a big round picture with the name underneath, like pinned conversations in
Messages. Click it to open the conversation; right-click it to **Unpin** or delete it.

### How it's stored

A new `pins` table holds each pinned conversation's key and a `position`. A new pin goes after
the others (`MAX(position) + 1`), so the grid keeps the order you pinned them in. Pinning
something already pinned leaves it where it is. Older databases get the table when Lime starts,
since it's created with `CREATE TABLE IF NOT EXISTS`. Deleting a conversation also unpins it, so
no empty tile is left behind.

Like Messages, at most nine conversations can be pinned (three rows of three, `MAX_PINS` in
`store.py`). With nine pinned, **Pin** is greyed out and its tooltip says to unpin one first.

### How it's shown

- The grid is a `Gtk.FlowBox` with exactly three per row, above the conversation list, in the
  same scrolling sidebar. Pinned conversations are left out of the list below.
- An unread pinned conversation gets the blue unread dot on its picture's top-left corner. A
  border in the background colour separates it from the picture.
- The open conversation's tile gets the same grey background as a selected row.
  `highlight_current_pin()` only changes style classes and doesn't rebuild the sidebar,
  because rebuilding a widget from inside its own click handler crashes GTK. That's the same
  reason `open_conversation` already defers its sidebar refresh.
- **Searching** hides the grid and shows pinned conversations in the results like any other,
  so they can still be found by name, number or message text.

### Testing

`tests/test_pins.py` covers pin order, pinning twice, unpinning and re-pinning (it goes last),
the nine-pin limit, deleting a pinned conversation, and pins surviving a restart.
`tools/screenshots.py` now pins Maya, Sam and Dad, and I rendered the real window with them: Maya
highlighted as the open chat, and Sam showing the unread dot.

### Later fixes to link previews

- **A picture the site refused is tried again.** If downloading the picture fails, for example
  with "429 Too Many Requests", the preview is still saved and shown with its title, and
  `image_failed` records the time. After an hour (`RETRY_IMAGE`), `cached()` reports nothing
  saved, so the link is fetched again. A picture that isn't an image, or is too big, is still
  skipped for good, because downloading it again won't change that.
- **Quitting no longer waits for slow websites.** Previews used to download on a
  `ThreadPoolExecutor`. Python waits for those threads to finish before exiting, so quitting
  during a slow download could take up to the 10-second timeout. Each download now runs on its
  own daemon thread, which Python doesn't wait for. A `BoundedSemaphore(4)` still limits them to
  four at once.

## Release 1.1.0

The store listing (`data/…metainfo.xml`) gets a 1.1.0 release entry listing the new features,
and the new features are added to its feature list. Its privacy sentence said everything stays
between the phone and the computer; with link previews that's no longer exactly true, so it now
says link previews are the one thing that goes online, and that they can be turned off.

## Extra: Windows version

Lime now also runs on Windows. The window and everything in it are the same GTK code; what
changed is how Lime talks to the iPhone.

### Why Bluetooth needed new code

On Linux, Lime doesn't speak Bluetooth MAP itself. BlueZ's `obexd` does, and Lime asks it to
over D-Bus ("list the inbox", "push this message"). Windows has nothing like obexd: there's no
built-in MAP client to ask. So Lime now has its own:

- `obex.py` is OBEX, the small request/reply protocol both MAP (messages) and PBAP (contacts)
  run on. A request is a packet of typed headers (Name, Type, Body, …); long replies come back
  in several packets, each answered with "continue" until the last one says "success".
- `bluetooth.py` opens the RFCOMM socket OBEX runs over. A service like MAP sits on a numbered
  RFCOMM channel that you look up with SDP. On Windows, Winsock does the lookup itself when
  given the service's UUID. Python's `socket.connect` can't pass a UUID, so Lime calls Winsock's
  `connect` through ctypes. On Linux it asks the phone's SDP server directly, which is only
  used for testing the Windows code on Linux.
- `native_client.py` is MAP and PBAP on top of those, with the same signals and methods as
  `map_client.MapClient` and `contacts.ContactSync`, so `app.py` just picks one at startup.

OBEX allows one request at a time, so all of a connection's requests go through one worker
thread, and their results come back to the GTK main loop with `GLib.idle_add`. The message
store's SQLite connection belongs to the main thread, so the "do we already have this
message?" check stays on the main thread too.

### Why Lime publishes Bluetooth services on Windows (1.2.1)

The first Windows release couldn't connect: the iPhone answered "Not Authorized", and its
Bluetooth settings for the PC had no **Show Notifications** switch. The iPhone only offers
that switch (and **Sync Contacts**) to a computer whose SDP records, the list of services a
Bluetooth device publishes, include a MAP notification server and a PBAP client. On Linux,
BlueZ publishes both, which is why it worked there. Windows publishes neither.

So Lime now publishes them itself while it runs (`bluetooth.advertise`). It builds the two SDP
records byte by byte, modelled on BlueZ's, and registers them with Winsock's
`WSASetService`. The iPhone reads a computer's records when pairing, so a PC paired before
this needs to be paired again with Lime open.

The notification server is real, not just a record. It listens on an RFCOMM channel, and after
connecting Lime sends the iPhone a `SetNotificationRegistration` request. The iPhone then
connects back and PUTs an event report for each new message (`obex.serve` answers it), and Lime
lists and fetches straight away. Polling every 10 seconds stays as a fallback, and is still
what's used on Linux with `LIME_NATIVE_BLUETOOTH=1`, where obexd owns the notification server.

### Other Windows differences

- **Notifications** are Windows toasts, shown through PowerShell so no extra library is
  needed. The installer gives the Start menu shortcut Lime's app ID; that's what lets toasts
  show as "Lime" instead of "Windows PowerShell".
- **One running copy.** On Linux, `Gtk.Application` makes sure only one Lime runs, using
  D-Bus. On Windows the first copy listens on a localhost port, and starting Lime again just
  tells that copy to show its window. That matters because closing the window keeps Lime
  running in the background.
- **Spell check** loads Enchant by its Windows DLL name too.

### How it's built

`windows/build.sh` runs in MSYS2, which provides GTK, PyGObject and Enchant for Windows.
PyInstaller bundles Python and those libraries into `dist/Lime`, and Inno Setup turns that
into an installer. The `Windows build` GitHub workflow does this for every push and attaches
the installer to a release when a `v*` tag is pushed. Before uploading, it runs the bundled
`Lime.exe --self-test`, which checks that GTK, the native Bluetooth client and spell check
all load.
