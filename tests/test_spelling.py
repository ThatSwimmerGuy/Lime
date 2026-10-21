import pytest

from phonemessages import spelling
from phonemessages.spelling import correction, edit_distance, misspelled, word_before

# A tiny fake dictionary standing in for Enchant.
WORDS = {"the", "receive", "tomorrow", "hello", "there", "definitely", "see", "you", "at",
         "to", "meet", "Monday", "on", "and", "Jhon", "a", "lot", "is", "it", "this"}
SUGGESTIONS = {
    "teh": ["the", "ten", "tea"],
    "recieve": ["receive", "relieve"],
    "tomorow": ["tomorrow"],
    "definately": ["definitely", "defiantly"],
    "monday": ["Monday"],
    "xqzv": ["quiz"],          # too far from the typed word: must not be used
    "helo": ["hello", "help"],
    "thier": ["their", "there"],
}


def check(word):
    return word in WORDS or word.lower() in WORDS


def suggest(word):
    return SUGGESTIONS.get(word.lower(), [])


def fix(text, word=None, ignored=()):
    """Correction for the last word in `text`, the way the compose box asks for it."""
    start = text.rindex(word) if word else text.rindex(text.split()[-1])
    word = word or text.split()[-1]
    return correction(word, text, start, check, suggest, ignored)


# -- edit_distance -------------------------------------------------------

@pytest.mark.parametrize("a, b, d", [
    ("the", "the", 0), ("teh", "the", 1), ("helo", "hello", 1), ("recieve", "receive", 1),
    ("definately", "definitely", 1), ("kitten", "sitting", 3), ("", "abc", 3),
])
def test_edit_distance(a, b, d):
    assert edit_distance(a, b) == d


# -- correction ----------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("teh", "the"),
    ("i will recieve", "receive"),
    ("see you tomorow", "tomorrow"),
    ("this is definately", "definitely"),
    ("see you on monday", "Monday"),  # case-only fix from the dictionary
])
def test_fixes_misspellings(text, expected):
    assert fix(text) == expected


def test_keeps_capital_at_sentence_start():
    assert fix("Teh") == "The"
    assert fix("ok. Teh") == "The"


@pytest.mark.parametrize("text, expected", [
    ("i", "I"), ("im", "I'm"), ("Im", "I'm"), ("dont", "don't"), ("i cant", "can't"),
    ("youre", "you're"), ("thats", "that's"),
])
def test_chat_shorthand(text, expected):
    assert fix(text) == expected


@pytest.mark.parametrize("text", [
    "hello",          # spelled right
    "xqzv",           # only suggestion is too different
    "id",             # a real word, not "I'd"
    "ill",            # a real word, not "I'll"
    "I",              # already right
    "NASA",           # acronym
    "LOL",
    "see you Jhonny",  # capitalised mid-sentence: probably a name
    "at",             # too short to guess at
])
def test_leaves_alone(text):
    assert fix(text) is None


@pytest.mark.parametrize("text, word", [
    ("mail me at jhon@exmaple.com", "exmaple"),
    ("go to https://exmaple.com/page", "exmaple"),
    ("www.exmaple.com", "exmaple"),
])
def test_never_touches_links_or_addresses(text, word):
    assert fix(text, word) is None


def test_ignored_words_are_left_alone():
    assert fix("teh", ignored={"teh"}) is None


def test_curly_apostrophe_shorthand():
    assert fix("I dont") == "don't"


def test_picks_first_close_suggestion():
    assert fix("helo") == "hello"


# -- word_before ---------------------------------------------------------

def test_word_before_cursor():
    text = "see you tomorow "
    assert word_before(text, len(text) - 1) == (8, "tomorow")


def test_word_before_handles_apostrophes():
    assert word_before("I don't", 7) == (2, "don't")


def test_no_word_before_cursor():
    assert word_before("hello ", 6) is None  # cursor is after the space, not after a word
    assert word_before("", 0) is None


# -- misspelled ----------------------------------------------------------

def test_misspelled_spans():
    text = "teh cat is definately here"
    known = WORDS | {"cat", "here"}
    assert misspelled(text, lambda w: w in known) == [(0, 3), (11, 21)]


def test_word_being_typed_is_not_flagged():
    text = "hello teh"
    assert misspelled(text, check, cursor=len(text)) == []
    assert misspelled(text, check, cursor=None) == [(6, 9)]


def test_misspelled_skips_names_links_shorthand_and_ignored():
    text = "see Jhonny at www.exmaple.com dont teh"
    assert misspelled(text, check, ignored={"teh"}) == []


# -- languages -----------------------------------------------------------

def test_default_languages_from_locale(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    assert spelling.default_languages() == ["en_GB", "en", "en_US"]


def test_default_languages_ignores_c_locale(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "C.UTF-8")
    assert spelling.default_languages() == ["en_US", "en"]
