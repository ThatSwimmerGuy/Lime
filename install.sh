#!/bin/sh
# Adds Lime to your app launcher, for your user only. Run with --uninstall to remove it.
# (To install the Flatpak instead, see the README.)
set -e
id=io.github.ThatSwimmerGuy.Lime
here="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$data/applications"
icons="$data/icons/hicolor/scalable/apps"

# launcher files from before Lime had its Flathub ID
rm -f "$apps/local.Lime.desktop" "$icons/lime.svg"

if [ "$1" = "--uninstall" ]; then
    rm -f "$apps/$id.desktop" "$icons/$id.svg"
    update-desktop-database -q "$apps" 2>/dev/null || true
    echo "Removed Lime from your app launcher."
    echo "Your messages and settings are still in $data/phone-messages and ~/.config/phone-messages."
    exit 0
fi

mkdir -p "$apps" "$icons"
sed "s|^Exec=.*|Exec=\"$here/phone-messages\"|" "$here/data/$id.desktop" > "$apps/$id.desktop"
cp "$here/icons/lime.svg" "$icons/$id.svg"
gtk-update-icon-cache -q -t "$data/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$apps" 2>/dev/null || true
echo "Lime is now in your app launcher. You can also start it with: $here/phone-messages"
