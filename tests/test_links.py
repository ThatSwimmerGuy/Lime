import pytest

from phonemessages import links

MAPS_IMAGE = ("https://maps.google.com/maps/api/staticmap?center=47.6205063%2C-122.3518523"
              "&amp;zoom=17&amp;size=900x900")


def page(head):
    return "<html><head>%s</head><body><p>Hello</p></body></html>" % head


# -- finding the link ------------------------------------------------------------

@pytest.mark.parametrize("text, url", [
    ("look https://example.com/a?b=1 cool", "https://example.com/a?b=1"),
    ("https://example.com.", "https://example.com"),
    ("(see https://example.com/x)", "https://example.com/x"),
    ("https://en.wikipedia.org/wiki/Lime_(fruit)", "https://en.wikipedia.org/wiki/Lime_(fruit)"),
    ("meet here: https://maps.app.goo.gl/AbC123!", "https://maps.app.goo.gl/AbC123"),
    ("go to www.example.com", "https://www.example.com"),
    ("HTTP://EXAMPLE.COM", "HTTP://EXAMPLE.COM"),
])
def test_find_url(text, url):
    assert links.find_url(text) == url


@pytest.mark.parametrize("text", ["no link here", "example.com", "", None, "email me@example.com"])
def test_find_url_without_a_link(text):
    assert links.find_url(text) is None


def test_find_url_takes_the_first_link():
    assert links.find_url("https://one.com and https://two.com") == "https://one.com"


# -- reading the page -------------------------------------------------------------

def test_parse_open_graph_tags():
    html = page('<meta property="og:title" content="Rick &amp; Morty">'
                '<meta property="og:site_name" content="YouTube">'
                '<meta property="og:image" content="https://i.ytimg.com/vi/x.jpg">'
                '<title>Ignored - YouTube</title>')
    assert links.parse(html, "https://www.youtube.com/watch?v=x") == {
        "url": "https://www.youtube.com/watch?v=x", "title": "Rick & Morty",
        "site": "YouTube", "image": "https://i.ytimg.com/vi/x.jpg"}


def test_parse_falls_back_to_twitter_tags_title_and_domain():
    html = page('<meta name="twitter:image" content="/card.png"><title>\n  My   Blog\n</title>')
    p = links.parse(html, "https://www.example.com/post/1")
    assert (p["title"], p["site"], p["image"]) == ("My Blog", "example.com", "https://www.example.com/card.png")


def test_parse_ignores_tags_in_the_body():
    html = page("<title>Real</title>").replace("<p>Hello</p>", '<meta property="og:title" content="Fake">')
    assert links.parse(html, "https://example.com")["title"] == "Real"


def test_parse_page_without_anything():
    assert links.parse("<html></html>", "https://example.com") == {
        "url": "https://example.com", "title": None, "site": "example.com", "image": None}


# -- Google Maps ------------------------------------------------------------------

@pytest.mark.parametrize("url, name", [
    ("https://www.google.com/maps/place/Space+Needle/@47.62,-122.35,17z/data=!3m1", "Space Needle"),
    ("https://www.google.com/maps/place/Caf%C3%A9+Lime/@1,2,3z", "Café Lime"),
    ("https://www.google.com/maps?q=Eiffel+Tower", "Eiffel Tower"),
    ("https://maps.google.com/?q=Pike+Place", "Pike Place"),
    ("https://www.google.com/maps/search/?api=1&query=pizza", "pizza"),
    ("https://www.google.com/maps/@47.62,-122.35,15z", None),
    ("https://www.google.com/search?q=maps", None),
    ("https://example.com/maps/place/Nope", None),
])
def test_google_maps_place(url, name):
    assert links.google_maps_place(url) == name


def test_parse_google_maps_uses_the_place_name():
    html = page('<meta content="Google Maps" property="og:title">'
                '<meta content="%s" property="og:image">' % MAPS_IMAGE)
    p = links.parse(html, "https://www.google.com/maps/place/Space+Needle/@47.62,-122.35,17z")
    assert (p["title"], p["site"]) == ("Space Needle", "Google Maps")
    assert p["image"] == MAPS_IMAGE.replace("&amp;", "&")


def test_parse_google_maps_drops_a_map_of_nowhere():
    html = page('<meta content="Google Maps" property="og:title">'
                '<meta content="https://maps.google.com/maps/api/staticmap?center=0.0%2C0.0&amp;zoom=12"'
                ' property="og:image">')
    p = links.parse(html, "https://www.google.com/maps/place/Somewhere")
    assert (p["title"], p["image"]) == ("Somewhere", None)


# -- downloading and caching ------------------------------------------------------

class FakeWeb:
    """Stands in for the internet: {url: (final url, content type, body)}."""

    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def __call__(self, url, limit):
        self.asked.append(url)
        if url not in self.pages:
            raise OSError("no such page")
        final, kind, body = self.pages[url]
        return final, kind, body[:limit]


@pytest.fixture
def web():
    return FakeWeb({
        "https://maps.app.goo.gl/AbC": (
            "https://www.google.com/maps/place/Space+Needle/@47.62,-122.35,17z", "text/html; charset=utf-8",
            page('<meta content="Google Maps" property="og:title"><meta content="%s" property="og:image">'
                 % MAPS_IMAGE).encode()),
        MAPS_IMAGE.replace("&amp;", "&"): ("", "image/png", b"\x89PNG fake"),
        "https://example.com/doc.pdf": ("https://example.com/doc.pdf", "application/pdf", b"%PDF"),
        "https://example.com/bare": ("https://example.com/bare", "text/html", b"<html></html>"),
    })


def test_fetch_follows_the_short_link_and_saves_the_picture(tmp_path, web):
    previews = links.Previews(str(tmp_path), web)
    p = previews.fetch("https://maps.app.goo.gl/AbC")
    assert (p["url"], p["title"], p["site"]) == ("https://maps.app.goo.gl/AbC", "Space Needle", "Google Maps")
    with open(p["image_path"], "rb") as f:
        assert f.read() == b"\x89PNG fake"
    assert previews.cached("https://maps.app.goo.gl/AbC") == p


def test_cached_link_is_not_downloaded_again(tmp_path, web):
    links.Previews(str(tmp_path), web).fetch("https://maps.app.goo.gl/AbC")
    again = links.Previews(str(tmp_path), web)  # as after restarting Lime
    assert again.cached("https://maps.app.goo.gl/AbC")["title"] == "Space Needle"
    assert web.asked.count("https://maps.app.goo.gl/AbC") == 1


def test_nothing_cached_yet(tmp_path, web):
    assert links.Previews(str(tmp_path), web).cached("https://example.com") is None


@pytest.mark.parametrize("url", ["https://example.com/doc.pdf", "https://example.com/bare",
                                 "https://example.com/missing"])
def test_link_without_a_preview_is_remembered_as_failed(tmp_path, web, url):
    previews = links.Previews(str(tmp_path), web)
    assert previews.fetch(url)["failed"]
    assert previews.cached(url)["failed"]


def test_failed_link_is_tried_again_the_next_day(tmp_path, web, monkeypatch):
    previews = links.Previews(str(tmp_path), web)
    monkeypatch.setattr(links.time, "time", lambda: 1_790_000_000)
    previews.fetch("https://example.com/missing")
    monkeypatch.setattr(links.time, "time", lambda: 1_790_000_000 + links.RETRY_FAILED + 1)
    assert previews.cached("https://example.com/missing") is None


def test_picture_that_is_not_an_image_is_skipped(tmp_path, web):
    web.pages[MAPS_IMAGE.replace("&amp;", "&")] = ("", "text/html", b"<html>error</html>")
    p = links.Previews(str(tmp_path), web).fetch("https://maps.app.goo.gl/AbC")
    assert p["title"] == "Space Needle" and p["image_path"] is None


def test_picture_the_site_refused_keeps_the_title_and_is_retried_later(tmp_path, web, monkeypatch):
    image = MAPS_IMAGE.replace("&amp;", "&")
    del web.pages[image]  # the download raises, like a "429 Too Many Requests"
    previews = links.Previews(str(tmp_path), web)
    monkeypatch.setattr(links.time, "time", lambda: 1_790_000_000)
    p = previews.fetch("https://maps.app.goo.gl/AbC")
    assert p["title"] == "Space Needle" and p["image_path"] is None
    assert previews.cached("https://maps.app.goo.gl/AbC")["title"] == "Space Needle"  # shown meanwhile
    monkeypatch.setattr(links.time, "time", lambda: 1_790_000_000 + links.RETRY_IMAGE + 1)
    assert previews.cached("https://maps.app.goo.gl/AbC") is None  # time to try again
    web.pages[image] = ("", "image/png", b"\x89PNG fake")
    assert previews.fetch("https://maps.app.goo.gl/AbC")["image_path"]


def test_picture_that_is_not_an_image_is_not_retried(tmp_path, web, monkeypatch):
    web.pages[MAPS_IMAGE.replace("&amp;", "&")] = ("", "text/html", b"<html>error</html>")
    previews = links.Previews(str(tmp_path), web)
    previews.fetch("https://maps.app.goo.gl/AbC")
    monkeypatch.setattr(links.time, "time", lambda: 1_790_000_000 + links.RETRY_FAILED * 10)
    assert previews.cached("https://maps.app.goo.gl/AbC")["title"] == "Space Needle"
