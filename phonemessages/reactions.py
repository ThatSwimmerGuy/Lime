"""Tapback reactions as text.

Bluetooth can't send real iMessage tapbacks, so reactions travel as the text an
iPhone uses for non-iMessage contacts, e.g. 'Loved “How was your day?”'.
Incoming reactions arrive the same way and are turned back into badges.
"""
import re
from collections import namedtuple

# emoji, verb used in the message text, name used in "Removed a … from"
TAPBACKS = [
    ("❤️", "Loved", "heart"),
    ("👍", "Liked", "like"),
    ("👎", "Disliked", "dislike"),
    ("😂", "Laughed at", "laugh"),
    ("‼️", "Emphasized", "exclamation"),
    ("❓", "Questioned", "question mark"),
]
_BY_VERB = {verb.lower(): emoji for emoji, verb, _ in TAPBACKS}
_BY_NAME = {name: emoji for emoji, _, name in TAPBACKS}

# Optional sender name of up to three words (group chats), then the verb and the quote.
_WHO = r"(?:(?P<who>\S+(?: \S+){0,2}) )?"
_QUOTE = r"[“\"](?P<quote>.*)[”\"]"
REACT_RE = re.compile(_WHO + r"(?P<verb>loved|liked|disliked|laughed at|emphasized|questioned"
                      r"|reacted (?P<emoji>\S+) to) " + _QUOTE + r"$", re.S | re.I)
REMOVE_RE = re.compile(_WHO + r"removed an? (?P<kind>.+?) (?:reaction )?from " + _QUOTE + r"$", re.S | re.I)

Reaction = namedtuple("Reaction", "emoji quote removed")


def wire_text(emoji, target_text):
    """The text the phone sends for a reaction."""
    for e, verb, _ in TAPBACKS:
        if e == emoji:
            return "%s “%s”" % (verb, target_text)
    return "Reacted %s to “%s”" % (emoji, target_text)


def parse(text):
    """Reaction if `text` looks like one, else None."""
    m = REACT_RE.match(text.strip())
    if m:
        emoji = m.group("emoji") or _BY_VERB[m.group("verb").lower()]
        return Reaction(emoji, m.group("quote"), False)
    m = REMOVE_RE.match(text.strip())
    if m:
        kind = m.group("kind").lower()
        return Reaction(_BY_NAME.get(kind, kind), m.group("quote"), True)
    return None


def _norm(text):
    return " ".join(text.replace("’", "'").replace("“", '"').replace("”", '"').split())


def find_target(messages, quote):
    """Id of the newest message whose text the quote refers to, or None.

    Only a real match counts, so ordinary messages like 'I liked “Dune”' are left alone.
    """
    q = _norm(quote)
    truncated = q.endswith("…") or q.endswith("...")
    q = q.rstrip(".…").rstrip()
    if not q:
        return None
    for m in reversed(messages):
        t = _norm(m["text"])
        if t == q or ((truncated or len(q) >= 20) and t.startswith(q)):
            return m["id"]
    return None
