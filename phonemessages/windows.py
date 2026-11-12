"""Windows stand-ins for what the Linux desktop provides: toast notifications, the taskbar
identity, and a single running copy (GApplication does that over D-Bus, which Windows lacks)."""
import base64
import ctypes
import os
import socket
import subprocess
import threading
from xml.sax.saxutils import escape, quoteattr

from gi.repository import GLib

# PowerShell's own ID, which Windows always accepts, for when Lime has no Start menu
# shortcut carrying its ID (a portable copy rather than an installed one)
FALLBACK_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

TOAST_SCRIPT = """
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s')))
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def set_app_id(app_id):
    """Group Lime's windows under its own taskbar button and name."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def _installed():
    """Whether the installer made the Start menu shortcut toasts need to show as 'Lime'."""
    for base in (os.environ.get("APPDATA"), os.environ.get("PROGRAMDATA")):
        if base and os.path.exists(os.path.join(base, "Microsoft", "Windows", "Start Menu",
                                                "Programs", "Lime.lnk")):
            return True
    return False


def notify(app_id, title, body, icon_path=None):
    """Show a toast notification. Runs PowerShell in the background, so it never blocks."""
    image = ""
    if icon_path and os.path.isabs(icon_path):
        image = '<image placement="appLogoOverride" hint-crop="circle" src=%s/>' % quoteattr(
            "file:///" + icon_path.replace("\\", "/"))
    xml = ('<toast><visual><binding template="ToastGeneric"><text>%s</text><text>%s</text>%s'
           '</binding></visual></toast>') % (escape(title), escape(body[:300]), image)
    script = TOAST_SCRIPT % (base64.b64encode(xml.encode()).decode(),
                             app_id if _installed() else FALLBACK_APP_ID)

    def run():
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                            base64.b64encode(script.encode("utf-16-le")).decode()],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    threading.Thread(target=run, daemon=True).start()


class SingleInstance:
    """The first copy of Lime listens on a localhost port, written to `port_file`; later copies
    find it there, ask it to show its window, and quit."""

    def __init__(self, port_file):
        self.port_file = port_file
        self.server = None

    def hand_over(self):
        """True if another copy is running and has been told to show itself."""
        try:
            with open(self.port_file) as f:
                port = int(f.read().strip())
            with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
                s.sendall(b"activate\n")
                return s.recv(16).startswith(b"ok")
        except (OSError, ValueError):
            return False

    def listen(self, on_activate):
        """Start answering later copies; on_activate() runs on the main thread."""
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        os.makedirs(os.path.dirname(self.port_file), exist_ok=True)
        with open(self.port_file, "w") as f:
            f.write(str(self.server.getsockname()[1]))

        def serve():
            while True:
                try:
                    conn, _ = self.server.accept()
                except OSError:
                    return
                with conn:
                    try:
                        conn.settimeout(2)
                        if conn.recv(64).startswith(b"activate"):
                            GLib.idle_add(lambda: on_activate() and False)
                            conn.sendall(b"ok\n")
                    except OSError:
                        pass
        threading.Thread(target=serve, daemon=True).start()
