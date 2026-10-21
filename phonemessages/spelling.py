"""Spell checking and autocorrect for the compose box.

Uses the Enchant spelling library (libenchant-2) directly through ctypes, so it needs no
Python packages. Enchant and its Hunspell dictionaries ship in the GNOME Flatpak runtime;
from source, install them with your distro (see README). Without them, Speller.load()
returns None and the compose box simply has no spelling features.

The decision logic (which word to fix, what to fix it to) is plain functions that take
`check` and `suggest` callables, so it can be tested without Enchant.
"""
import ctypes
import os
import re

# Common chat shorthand the dictionary may not fix the way people expect.
SHORTHAND = {
    "i": "I", "im": "I'm", "ive": "I've", "id": None, "ill": None,  # None: real words, leave alone
    "dont": "don't", "cant": "can't", "wont": "won't", "didnt": "didn't", "doesnt": "doesn't",
    "isnt": "isn't", "wasnt": "wasn't", "arent": "aren't", "werent": "weren't",
    "couldnt": "couldn't", "shouldnt": "shouldn't", "wouldnt": "wouldn't",
    "havent": "haven't", "hasnt": "hasn't", "hadnt": "hadn't",
    "thats": "that's", "whats": "what's", "theres": "there's", "youre": "you're",
    "theyre": "they're", "youve": "you've", "theyve": "they've", "weve": "we've",
}

# A word: letters, optionally joined by apostrophes (don't, rock'n'roll). No digits.
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# Characters that end a word and trigger autocorrect, like on a Mac.
BOUNDARY = set(" \t.,!?;:)\"”")


def edit_distance(a, b):
    """Damerau-Levenshtein distance: swapping two neighbouring letters counts as one edit."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            row[j] = min(rows[i - 1][j] + 1, row[j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], rows[i - 2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


def at_sentence_start(text, start):
    before = text[:start].rstrip()
    return not before or before[-1] in ".!?\n"


def skip_word(word, text, start):
    """Words spelling should leave alone: acronyms, names, and parts of links or addresses."""
    if len(word) > 1 and word.isupper():
        return True  # NASA, LOL
    if word[0].isupper() and not at_sentence_start(text, start):
        return True  # probably a name
    end = start + len(word)
    chunk_start = max(text.rfind(c, 0, start) for c in " \t\n") + 1
    chunk_end = min([i for i in (text.find(c, end) for c in " \t\n") if i != -1] or [len(text)])
    chunk = text[chunk_start:chunk_end]
    return "@" in chunk or "://" in chunk or chunk.lower().startswith("www.") or "/" in chunk


def match_case(original, replacement):
    if original[0].isupper() and replacement[0].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


def correction(word, text, start, check, suggest, ignored=()):
    """What to replace `word` (at `start` in `text`) with, or None to leave it."""
    if not word or word.lower() in ignored or skip_word(word, text, start):
        return None
    key = word.lower().replace("’", "'")
    if key in SHORTHAND:
        fix = SHORTHAND[key]
        return match_case(word, fix) if fix and fix != word else None
    if len(word) < 3 or check(word):
        return None
    limit = 1 if len(word) <= 4 else 2  # short words have many near neighbours
    for candidate in suggest(word)[:3]:
        if candidate == word:
            continue
        if edit_distance(word.lower(), candidate.lower()) <= limit:
            return match_case(word, candidate)
    return None


def word_before(text, cursor):
    """(start, word) for the word that ends right before `cursor`, or None."""
    for m in WORD_RE.finditer(text, 0, cursor):
        if m.end() == cursor:
            return m.start(), m.group()
    return None


def misspelled(text, check, cursor=None, ignored=()):
    """[(start, end)] of misspelled words. The word being typed at `cursor` isn't flagged yet."""
    spans = []
    for m in WORD_RE.finditer(text):
        word = m.group()
        if m.end() == cursor or len(word) < 2 or word.lower() in ignored:
            continue
        if skip_word(word, text, m.start()) or word.lower().replace("’", "'") in SHORTHAND:
            continue
        if not check(word):
            spans.append((m.start(), m.end()))
    return spans


def default_languages():
    """Dictionary names to try, from the user's locale: en_GB.UTF-8 -> en_GB, en."""
    langs = []
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        for value in os.environ.get(var, "").split(":"):
            code = value.split(".")[0].split("@")[0]
            if code and code not in ("C", "POSIX"):
                langs += [code, code.split("_")[0]]
    return list(dict.fromkeys(langs + ["en_US", "en"]))


class Speller:
    """A dictionary from Enchant. Use Speller.load(), which returns None if Enchant is missing."""

    def __init__(self, lib, broker, dictionary, language):
        self._lib, self._broker, self._dict, self.language = lib, broker, dictionary, language

    @classmethod
    def load(cls, languages=None):
        try:
            lib = ctypes.CDLL("libenchant-2.so.2")
        except OSError:
            return None
        lib.enchant_broker_init.restype = ctypes.c_void_p
        lib.enchant_broker_dict_exists.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.enchant_broker_request_dict.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.enchant_broker_request_dict.restype = ctypes.c_void_p
        lib.enchant_dict_check.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ssize_t]
        lib.enchant_dict_suggest.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ssize_t,
                                             ctypes.POINTER(ctypes.c_size_t)]
        lib.enchant_dict_suggest.restype = ctypes.POINTER(ctypes.c_char_p)
        lib.enchant_dict_free_string_list.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
        lib.enchant_dict_add.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ssize_t]
        broker = lib.enchant_broker_init()
        if not broker:
            return None
        for lang in languages or default_languages():
            if lib.enchant_broker_dict_exists(broker, lang.encode()):
                dictionary = lib.enchant_broker_request_dict(broker, lang.encode())
                if dictionary:
                    return cls(lib, broker, dictionary, lang)
        return None

    def check(self, word):
        data = word.encode("utf-8")
        return self._lib.enchant_dict_check(self._dict, data, len(data)) == 0

    def suggest(self, word):
        data = word.encode("utf-8")
        count = ctypes.c_size_t()
        result = self._lib.enchant_dict_suggest(self._dict, data, len(data), ctypes.byref(count))
        if not result:
            return []
        words = [result[i].decode("utf-8", "replace") for i in range(count.value)]
        self._lib.enchant_dict_free_string_list(self._dict, result)
        return words

    def learn(self, word):
        """Add to the user's personal dictionary, so it's never flagged or corrected again."""
        data = word.encode("utf-8")
        self._lib.enchant_dict_add(self._dict, data, len(data))
