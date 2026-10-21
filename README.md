<p align="center"><img src="icons/lime.svg" width="112" alt="Lime icon"></p>

# Lime

*Lime: Linux iPhone Messaging Engine*

Read and send your iPhone's messages from a Linux computer. Lime connects to the
iPhone over Bluetooth using the Message Access Profile (MAP), the same feature car
stereos and Microsoft Phone Link use. **The iPhone itself sends every message**,
so it goes out as an iMessage or SMS from your number, as if you'd typed it on the phone.

No Apple ID, no Mac, no cloud service: everything stays between your phone and your computer.

## Features

- **Read and reply** to your texts from your computer, with desktop notifications for new messages.
- **Your contacts.** Lime syncs the iPhone's phone book, so chats show names and photos. The
  new-message window lists all your contacts to pick from.
- **Reactions and replies.** Right-click a message to react (❤️ 👍 👎 😂 ‼️ ❓) or reply to it.
- **Delete chats.** Right-click a chat in the sidebar to remove it from your computer.
- **Make it yours.** Under Settings (⚙), choose your own bubble and text colours, and
  whether the window buttons sit on the left (Mac style) or the right.
- **Stays connected.** Lime reconnects on its own when the iPhone comes back in range, and
  keeps running in the background when you close the window, so you still get notifications.
- **Mac-inspired dark design**, with iOS-style bubbles and traffic-light window buttons.

## Requirements

- Linux with a Bluetooth adapter
- Python 3 with GTK 3 (PyGObject) and libnotify
- BlueZ with its OBEX service (`obexd`)
- An iPhone

## Install

### Flatpak

Lime is packaged as a Flatpak (`io.github.ThatSwimmerGuy.Lime`). Until it's available on Flathub,
you can build and install it from this repository:

```sh
flatpak install --user flathub org.flatpak.Builder
git clone https://github.com/ThatSwimmerGuy/Lime.git
cd Lime
flatpak run org.flatpak.Builder --user --install --force-clean build-dir flatpak/io.github.ThatSwimmerGuy.Lime.yml
```

Bluetooth itself runs outside the Flatpak, so your system still needs BlueZ and its OBEX
service: install `bluez` and `bluez-obex` (Arch) or `bluez-obexd` (Debian/Ubuntu/Fedora), and
make sure Bluetooth is running with `sudo systemctl enable --now bluetooth`.

### From source

#### 1. Install the dependencies

**Arch / Manjaro**

```sh
sudo pacman -S --needed python-gobject gtk3 libnotify bluez bluez-utils bluez-obex
```

**Debian / Ubuntu / Linux Mint**

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-notify-0.7 bluez bluez-obexd
```

**Fedora**

```sh
sudo dnf install python3-gobject gtk3 libnotify bluez bluez-obexd
```

Then make sure Bluetooth is running:

```sh
sudo systemctl enable --now bluetooth
```

#### 2. Download Lime

```sh
git clone https://github.com/ThatSwimmerGuy/Lime.git
cd Lime
```

#### 3. Add it to your app launcher

```sh
./install.sh
```

This adds Lime and its icon to your app menu, for your user only (no `sudo` needed).
To remove it again, run `./install.sh --uninstall`. You can also skip this step and start
Lime directly with `./phone-messages`.

## Set up your iPhone (one time)

1. **Pair the iPhone with your computer.** The easiest way is your desktop's Bluetooth
   settings (KDE, GNOME, etc.). Keep the iPhone's **Settings → Bluetooth** screen open while
   pairing, and confirm the code on both devices. Or pair from a terminal:

   ```sh
   bluetoothctl
   power on
   scan on            # wait until your iPhone appears, note its address
   pair XX:XX:XX:XX:XX:XX
   trust XX:XX:XX:XX:XX:XX
   quit
   ```

2. **Let the iPhone share messages.** On the iPhone, go to **Settings → Bluetooth → ⓘ next to
   your computer** and turn on **Show Notifications**. Without this, the iPhone won't share messages.

3. **Let it share contacts (optional).** On the same screen, turn on **Sync Contacts** so Lime
   shows names and photos instead of numbers.

4. **Connect.** Open Lime, choose your iPhone at the top left, and press **Connect**. If the
   iPhone asks whether to allow notifications, tap **Allow**.

## Using Lime

| To… | Do this |
| --- | --- |
| Open a chat | Click it in the sidebar |
| Start a new chat | Click ✏️, then pick a contact or type a number (with country code) or iMessage email |
| React or reply to a message | Right-click the message |
| Delete a chat | Right-click it in the sidebar → **Delete Conversation…** |
| Change colours or window-button side | Click ⚙ (Settings) |
| Search chats | Type in the search box above the chat list |
| Quit completely | Ctrl+Q (closing the window keeps Lime running for notifications) |

Deleting a chat only removes it from your computer. It stays on your iPhone.

### Where your data is kept

Everything is stored locally on your computer:

- Message history: `~/.local/share/phone-messages/messages.db`
- Contact photos: `~/.local/share/phone-messages/avatars/`
- Settings: `~/.config/phone-messages/config.json`

The Flatpak keeps its own copy of these under `~/.var/app/io.github.ThatSwimmerGuy.Lime/`.

## Limitations

These come from how the iPhone shares messages over Bluetooth, not from Lime:

- **No old history.** The iPhone only shares messages that arrive while it's connected. Lime
  keeps everything it receives from then on.
- **Messages you send from the phone itself** may not appear in Lime.
- **No photos or attachments.** The iPhone doesn't send pictures over Bluetooth, only the text
  "Attachment: 1 Image". Lime shows this as a 📷 Photo card so you know to check your phone.
  Sending pictures isn't possible either.
- **Reactions are sent as text.** Bluetooth can't send real iMessage tapbacks, so a reaction
  arrives as a line such as `Loved "How was your day?"`. Lime shows incoming ones as badges.
- **Group chats.** Replies go to the person, not the group.
- **Range.** The phone must be within Bluetooth range (about 10 m).

## Troubleshooting

- **The iPhone isn't in the list.** Pair it first (see above), then press the refresh button
  next to the device list.
- **Connected, but no messages arrive.** Check that **Show Notifications** is on for your
  computer in the iPhone's Bluetooth settings, then press Disconnect and Connect.
- **Numbers instead of names.** Turn on **Sync Contacts** in the same place, then reconnect.
- **"org.bluez.obex" errors.** The OBEX service isn't installed or running. Install
  `bluez-obex` (Arch) or `bluez-obexd` (Debian/Ubuntu/Fedora) and log out and back in.

## Project layout

```
phone-messages          launcher script (runs python3 -m phonemessages)
install.sh              adds/removes Lime in your app launcher (source install)
data/                   app launcher entry and app store metadata (metainfo)
flatpak/                Flatpak manifest and launcher
icons/lime.svg          app icon
screenshots/            app store screenshots
tools/screenshots.py    renders the screenshots from made-up demo data
phonemessages/
  app.py                window, sidebar, chat view, settings
  map_client.py         Bluetooth MAP connection to the iPhone (via BlueZ over D-Bus)
  contacts.py           phone book sync over Bluetooth PBAP
  bmessage.py           reading and writing the bMessage format MAP uses
  reactions.py          tapback reactions sent and received as text
  store.py              local SQLite message history
```

## License

[MIT](LICENSE)

Lime is an independent project and isn't affiliated with or endorsed by Apple.
iPhone and iMessage are trademarks of Apple Inc.
