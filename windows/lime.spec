# PyInstaller recipe for the Windows build. Run from an MSYS2 UCRT64 shell through
# windows/build.sh, which installs GTK, PyGObject and the rest first.
import glob
import os

prefix = os.environ.get("MINGW_PREFIX", "/ucrt64")
root = os.path.abspath(os.path.join(SPECPATH, ".."))
app_icon = "share/icons/hicolor/scalable/apps"

# the app icon is looked up by its app ID
icon_named = os.path.join(SPECPATH, "build", "io.github.ThatSwimmerGuy.Lime.svg")
os.makedirs(os.path.dirname(icon_named), exist_ok=True)
with open(os.path.join(root, "icons", "lime.svg"), "rb") as src, open(icon_named, "wb") as dst:
    dst.write(src.read())
datas = [(icon_named, app_icon),
         (os.path.join(prefix, "share", "icons", "hicolor", "index.theme"), "share/icons/hicolor"),
         (os.path.join(prefix, "etc", "ssl", "certs", "ca-bundle.crt"), "etc/ssl/certs")]

# spell check: Enchant, its Hunspell provider, and English dictionaries
binaries = [(os.path.join(prefix, "bin", "libenchant-2-2.dll"), ".")]
binaries += [(f, "lib/enchant-2") for f in glob.glob(os.path.join(prefix, "lib", "enchant-2", "*.dll"))]
for dic in glob.glob(os.path.join(prefix, "share", "hunspell", "en_*")):
    datas += [(dic, "share/hunspell"), (dic, "share/enchant-2/hunspell")]

a = Analysis(
    [os.path.join(SPECPATH, "lime.pyw")],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=["phonemessages.native_client", "phonemessages.windows", "phonemessages.bluetooth"],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "languages": ["en_US", "en_GB"],
            "module-versions": {"Gtk": "3.0", "GdkPixbuf": "2.0"},
        },
    },
    excludes=["tkinter", "gi.repository.Notify"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Lime",
    icon=os.path.join(SPECPATH, "lime.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Lime")
