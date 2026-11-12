"""Starts Lime on Windows (the .pyw extension means no console window)."""
import os
import sys

if getattr(sys, "frozen", False):  # inside the PyInstaller bundle
    here = sys._MEIPASS
    certs = os.path.join(here, "etc", "ssl", "certs", "ca-bundle.crt")
    if os.path.exists(certs):  # for link previews over https
        os.environ.setdefault("SSL_CERT_FILE", certs)
    os.environ.setdefault("XDG_DATA_DIRS", os.path.join(here, "share"))

if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
    # used by the CI build: check the bundle has everything, without opening a window
    import ctypes
    import glob
    import socket

    from phonemessages import app, spelling
    from gi.repository import Gtk  # after app, which picks the GTK version
    speller = spelling.Speller.load(["en_US"])
    enchant = []
    for name in ("libenchant-2-2.dll", "libenchant-2.dll"):
        try:
            ctypes.CDLL(name)
            enchant.append(name + " loads")
        except OSError as e:
            enchant.append("%s: %s" % (name, e))
    try:  # which plugins and dictionaries Enchant itself sees
        lib = ctypes.CDLL("libenchant-2-2.dll")
        lib.enchant_broker_init.restype = ctypes.c_void_p
        broker = ctypes.c_void_p(lib.enchant_broker_init())
        seen = []
        describe = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p)(
            lambda name, desc, path, data: seen.append("plugin " + name.decode()))
        lib.enchant_broker_describe(broker, describe, None)
        dicts = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                                 ctypes.c_void_p)(lambda tag, name, desc, path, data: seen.append("dict " + tag.decode()))
        lib.enchant_broker_list_dicts(broker, dicts, None)
        enchant.append(", ".join(seen) or "no plugins")
    except (OSError, AttributeError) as e:
        enchant.append(str(e))
    here = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    found = [os.path.relpath(f, here) for f in glob.glob(os.path.join(here, "**", "*enchant*"), recursive=True)
             + glob.glob(os.path.join(here, "**", "en_US.*"), recursive=True)
             + glob.glob(os.path.join(here, "**", "*hunspell*.dll"), recursive=True)]
    try:  # build machines usually have no Bluetooth, so this is only reported
        socket.socket(getattr(socket, "AF_BLUETOOTH", 32), socket.SOCK_STREAM,
                      getattr(socket, "BTPROTO_RFCOMM", 3)).close()
        bluetooth = "ok"
    except OSError as e:
        bluetooth = str(e)
    with open(sys.argv[2], "w") as f:
        f.write("gtk %d.%d\n" % (Gtk.get_major_version(), Gtk.get_minor_version()))
        f.write("client %s\n" % app.MapClient.__module__)
        f.write("spelling %s\n" % (speller.language if speller else "missing"))
        f.write("enchant %s\nfiles %s\n" % ("; ".join(enchant), ", ".join(found)))
        f.write("bluetooth sockets %s\n" % bluetooth)
    sys.exit(0)

from phonemessages.app import main  # noqa: E402

sys.exit(main())
