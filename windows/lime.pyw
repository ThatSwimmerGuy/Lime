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
    import socket

    from gi.repository import Gtk

    from phonemessages import app, spelling
    speller = spelling.Speller.load(["en_US"])
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
        f.write("bluetooth sockets %s\n" % bluetooth)
    sys.exit(0)

from phonemessages.app import main  # noqa: E402

sys.exit(main())
