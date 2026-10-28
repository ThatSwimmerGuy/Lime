"""Editing sent messages.

Bluetooth can't change a message that has already gone out, so an edit travels as a new
message starting with an asterisk ("*corrected text"), the usual way people fix a typo by
text. Lime remembers which message it corrects (`edit_of`) and shows the newest version in
the original bubble, marked "Edited".
"""


def wire_text(text):
    """The text the phone sends for an edit."""
    return "*" + text


def fold(msgs):
    """Fold edit messages into the ones they correct.

    Returns a list of dicts: the messages to show, where an edited one has its newest text in
    "text" and its earlier versions, oldest first, in "versions". Edits that failed to send are
    dropped, and the app reports those when they fail.
    """
    shown, by_id = [], {}
    for row in msgs:
        m = dict(row)
        target = by_id.get(m.get("edit_of"))
        if m.get("edit_of"):
            if target and m.get("status") != "failed":
                target["versions"].append(target["text"])
                target["text"] = m["text"]
            continue
        m["versions"] = []
        by_id[m["id"]] = m
        shown.append(m)
    return shown
