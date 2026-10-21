import pytest

from phonemessages import reactions
from phonemessages.reactions import Reaction


# -- outgoing: wire_text -------------------------------------------------

@pytest.mark.parametrize("emoji, expected", [
    ("❤️", "Loved “Dinner?”"),
    ("👍", "Liked “Dinner?”"),
    ("👎", "Disliked “Dinner?”"),
    ("😂", "Laughed at “Dinner?”"),
    ("‼️", "Emphasized “Dinner?”"),
    ("❓", "Questioned “Dinner?”"),
])
def test_wire_text_for_tapbacks(emoji, expected):
    assert reactions.wire_text(emoji, "Dinner?") == expected


def test_wire_text_for_other_emoji():
    assert reactions.wire_text("🎉", "We won") == "Reacted 🎉 to “We won”"


# -- incoming: parse -----------------------------------------------------

@pytest.mark.parametrize("emoji, _verb, _name", reactions.TAPBACKS)
def test_parse_reads_back_every_wire_text(emoji, _verb, _name):
    text = reactions.wire_text(emoji, "See you soon")
    assert reactions.parse(text) == Reaction(emoji, "See you soon", False)


def test_parse_custom_emoji_reaction():
    assert reactions.parse("Reacted 🎉 to “We won”") == Reaction("🎉", "We won", False)


def test_parse_accepts_straight_quotes_and_any_case():
    assert reactions.parse('LIKED "lunch?"') == Reaction("👍", "lunch?", False)


def test_parse_group_chat_sender_prefix():
    assert reactions.parse("Jane Doe loved “the photo”") == Reaction("❤️", "the photo", False)


@pytest.mark.parametrize("text, emoji", [
    ("Removed a heart from “hi”", "❤️"),
    ("Removed a like from “hi”", "👍"),
    ("Removed a dislike from “hi”", "👎"),
    ("Removed a laugh from “hi”", "😂"),
    ("Removed an exclamation from “hi”", "‼️"),
    ("Removed a question mark from “hi”", "❓"),
    ("Removed a 🎉 reaction from “hi”", "🎉"),
])
def test_parse_removals(text, emoji):
    assert reactions.parse(text) == Reaction(emoji, "hi", True)


@pytest.mark.parametrize("text", ["hello", "I loved it", "Loved", "", "Liked “unterminated"])
def test_parse_ordinary_text_is_not_a_reaction(text):
    assert reactions.parse(text) is None


def test_parse_quote_can_contain_quotes():
    assert reactions.parse('Loved “She said “hi” to me”').quote == "She said “hi” to me"


# -- find_target ---------------------------------------------------------

def msgs(*texts):
    return [{"id": i, "text": t} for i, t in enumerate(texts, start=1)]


def test_find_target_exact_match():
    assert reactions.find_target(msgs("hello", "Dinner?", "ok"), "Dinner?") == 2


def test_find_target_picks_the_newest_match():
    assert reactions.find_target(msgs("ok", "something", "ok"), "ok") == 3


def test_find_target_normalises_quotes_and_whitespace():
    assert reactions.find_target(msgs("It’s   “great”"), "It's \"great\"") == 1


def test_find_target_truncated_quote_matches_prefix():
    long = "This is a long message that the iPhone shortens when quoting"
    assert reactions.find_target(msgs(long), "This is a long…") == 1
    assert reactions.find_target(msgs(long), "This is a long...") == 1


def test_find_target_long_quote_matches_prefix_without_ellipsis():
    long = "Twenty characters or more get prefix matching"
    assert reactions.find_target(msgs(long), "Twenty characters or more") == 1


def test_find_target_short_quote_needs_exact_match():
    # 'I liked “Dune”' must not attach to a message that merely starts with "Dune"
    assert reactions.find_target(msgs("Dune was amazing"), "Dune") is None


@pytest.mark.parametrize("quote", ["", "…", "..."])
def test_find_target_empty_quote(quote):
    assert reactions.find_target(msgs("hello"), quote) is None


def test_reaction_round_trip_attaches_to_the_original():
    history = msgs("Are we still on for Friday?", "yes!")
    r = reactions.parse(reactions.wire_text("👍", history[0]["text"]))
    assert reactions.find_target(history, r.quote) == 1
