#!/bin/bash
# Builds Lime for Windows: dist/Lime (a folder that runs as is), Lime-<version>-portable.zip,
# and, if Inno Setup is installed, Lime-<version>-setup.exe.
# Run in an MSYS2 UCRT64 shell (https://www.msys2.org), from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

pacman -S --needed --noconfirm \
    "${MINGW_PACKAGE_PREFIX}-gtk3" \
    "${MINGW_PACKAGE_PREFIX}-python" \
    "${MINGW_PACKAGE_PREFIX}-python-gobject" \
    "${MINGW_PACKAGE_PREFIX}-python-pyinstaller" \
    "${MINGW_PACKAGE_PREFIX}-adwaita-icon-theme" \
    "${MINGW_PACKAGE_PREFIX}-librsvg" \
    "${MINGW_PACKAGE_PREFIX}-enchant" \
    "${MINGW_PACKAGE_PREFIX}-hunspell-en" \
    "${MINGW_PACKAGE_PREFIX}-ca-certificates" \
    zip

version=$(sed -n 's/.*<release version="\([^"]*\)".*/\1/p' data/io.github.ThatSwimmerGuy.Lime.metainfo.xml | head -1)
echo "Building Lime $version"

rm -rf build dist
python -m PyInstaller --noconfirm --distpath dist --workpath build windows/lime.spec

(cd dist && zip -qr "../Lime-$version-portable.zip" Lime)

iscc="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
if [ -x "$iscc" ]; then
    "$iscc" //Qp "//DVersion=$version" "//DSourceDir=$(cygpath -w "$PWD/dist/Lime")" \
        "//O$(cygpath -w "$PWD")" windows/lime.iss
else
    echo "Inno Setup not found; skipped the installer."
fi
ls -l Lime-"$version"-*
