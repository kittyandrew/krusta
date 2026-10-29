# The scenarios vm-kitter runs (vm.nix), after tests/record.py. Selenium on the host drives the VM's Firefox through
# geckodriver on a forwarded port, and the fake X's access log (fixture/server.py) shows what the page asked
# for. Every scenario runs even after one failed, so one run names every broken one; each failure leaves a
# screenshot and the page's HTML in $out, beside the machine's journal (Firefox's console and geckodriver) and
# Firefox's network log (/var/log/firefox).
# mypy: disable-error-code="name-defined"
# `machine`, `start_all` and `subtest` come from the test driver; `fail`, `guarded`, `collect`, `record` and the
# modules os, pathlib and traceback from record.py: the driver type-checks and lints the joined script, where every
# name is defined.
import json
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

SESSION, CSRF = "kitter-test-session", "kitter-test-csrf"  # the cookies server.py takes
PAGE1_CURSOR = "DAABCgABHVLny0q__6gKAAIdUsk9xdaAVggAAwAAAAIAAA"  # the recording's bottom cursor (pages.py)
# Posts of the recording (fixture/default.nix) and the two pages.py adds.
PLAIN = "2112986636392833489"  # Michael McFaul's, text only
ENTITIES = "2112996103201448049"  # Andrew S. Weiss's: two mentions and a link
HASHTAG = "2112987418152284605"  # AFP's #BREAKING, reposted by Julia Davis
GIF = "1000000000000000004"
HOSTILE_LINKS, HOSTILE_AUTHOR = "1000000000000000005", "1000000000000000006"  # links off x.com X would never send
HOSTILE_TEXT = "kitter test: @/kitter.test https://t.co/KitterJs"
LIST_ID, LIST_NAME = "1000000000000000099", "kitter test list"  # pages.py's pinned tabs
COMMUNITY_ID, COMMUNITY_NAME = "1000000000000000098", "kitter test community"
COMMUNITY_POST = "2112292195776508111"  # the recorded community's first post
PINNED = "2019881223666233717"  # the recorded profile's pinned post (@XDevelopers, user 2244994945)
QUOTING, QUOTED = "2112647302624002440", "2112645096063873329"  # a post of the recording, and the post it quotes
REPLY = "2103910018441769398"  # in the recorded posts and replies (the Replies tab), not in the recorded posts
# Recorded posts with X's ready translation into English: Unamuno's, in Spanish, reposted a day later by Toomas Ilves,
# and Barak Ravid's, in Hebrew, whose translation mentions @N12News.
SPANISH, HEBREW = "2112649305458983072", "2112984881110126881"
# Recorded authors with each badge: Polymarket's and the US mission's accounts also show their organisation.
GOLD, GREY, BLUE = "2112976973454524794", "2112986761055936551", "2112972948248125829"
DETAIL = "1649191520250245121"  # @XDevelopers' post whose page and replies the fake serves (fixture/server.py)
STRANGER = "1649255409897861120"  # @AlSultan_Meriam's reply on that page: "This is terrible!"
LOG = "/var/log/fake-x.log"
OUT = pathlib.Path(os.environ["out"])

browser: webdriver.Remote
driver_port = 0


def js(script: str, *args):
    return browser.execute_script(script, *args)


def page_state() -> str:
    """What the page shows, for a failure's message."""
    try:
        return json.dumps(
            js("""return {url: location.href, posts: document.querySelectorAll('article.post').length,
            error: document.querySelector('.error')?.textContent ?? null,
            button: document.querySelector('.more')?.textContent ?? null}""")
        )
    except WebDriverException as e:
        return f"unreadable: {e.msg}"


def wait(expression: str, seconds: float = 8):
    """The expression's value once truthy, polled in the page, for 8 s by default: short, as a caught plant mostly
    fails by waiting it out (Oct 28, 2026)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = js(f"try {{ return ({expression}) || null; }} catch (e) {{ return null; }}")
        except WebDriverException:
            value = None  # a navigation in progress
        if value is not None:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out after {seconds} s waiting for: {expression}; the page: {page_state()}")


def log_mark() -> int:
    return int(machine.succeed(f"wc -l < {LOG}"))


def requests(since: int) -> list[dict]:
    """The fake X's requests since `log_mark()` gave `since`. A line the fake is still writing waits for the next read."""
    lines = machine.succeed(f"tail -n +{since + 1} {LOG}").splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith("\n")]


def wait_request(since: int, test: Callable[[dict], bool], what: str, seconds: float = 8) -> dict:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if found := next((r for r in requests(since) if test(r)), None):
            return found
        time.sleep(0.2)
    raise AssertionError(f"no request for {what} within {seconds} s")


def go(to: str | Callable[[], object], until: str = "document.readyState !== 'loading'") -> None:
    """Opens the URL `to`, or runs `to` to leave the page, then waits for `until` in the next page. The page-load
    strategy is "none", so get() returns at once: a kitter page never finishes loading for WebDriver (content.js stops
    x.com's page). Marking the old document keeps every wait after this from passing on it. Skipping about:blank keeps
    it from passing on the blank page a navigation can show first, which a clean run took for the page a click opened
    (Oct 29, 2026)."""
    js("document.documentElement.dataset.left = ''")
    browser.get(to) if isinstance(to, str) else to()
    wait(f"document.documentElement.dataset.left === undefined && location.href !== 'about:blank' && {until}")


def open_feed() -> None:
    go("https://x.com/home")
    wait("document.querySelectorAll('article.post').length > 50")


def post(rest_id: str):
    """The post whose own byline links to `rest_id` (not a quote inside another), scrolled to the middle."""
    article = js(
        """const a = [...document.querySelectorAll('article.post > .byline a')]
            .find((a) => a.getAttribute('href').endsWith('/status/' + arguments[0]));
        const article = a?.closest('article.post');
        article?.scrollIntoView({block: 'center'});
        return article ?? null;""",
        rest_id,
    )
    assert article, f"post {rest_id} not shown; the page: {page_state()}"
    return article


def links(rest_id: str) -> list:
    return js(
        """return [...arguments[0].querySelector(':scope > .text').querySelectorAll('a')]
        .map((a) => [a.textContent, a.getAttribute('href'), a.target])""",
        post(rest_id),
    )


def start_browser() -> None:
    global browser
    options = webdriver.FirefoxOptions()
    options.add_argument("-headless")
    # Selenium's default overrides certificate errors, so a test CA Firefox does not trust would go unseen.
    options.accept_insecure_certs = False
    options.page_load_strategy = "none"  # see go()
    browser = webdriver.Remote(command_executor=f"http://127.0.0.1:{driver_port}", options=options)
    browser.set_window_size(1280, 900)
    # Firefox installs krusta by policy only once it runs, and a page opened before its content script is registered
    # stays x.com's own. Under load that took over 8 s in three of 73 plant sessions (Oct 29, 2026).
    end = time.monotonic() + 30
    while not chrome("return WebExtensionPolicy.getByID('krusta@kittyandrew')?.contentScripts.length > 0"):
        assert time.monotonic() < end, "krusta did not start within 30 s"
        time.sleep(0.1)
    go("https://x.com/settings")  # kitter's "not in kitter yet" page, which asks X nothing
    wait("document.querySelector('main.kitter')")
    # X's session as a signed-in browser holds it: `auth_token` out of the page's reach, `ct0` readable.
    browser.add_cookie({"name": "auth_token", "value": SESSION, "path": "/", "secure": True, "httpOnly": True})
    browser.add_cookie({"name": "ct0", "value": CSRF, "path": "/", "secure": True})
    browser.add_cookie({"name": "lang", "value": "uk", "path": "/", "secure": True})  # the account's language on x.com


def takeover() -> None:
    since = log_mark()
    open_feed()
    stray = [r["host"] + r["path"] for r in requests(since) if r["host"] == "abs.twimg.com" or r["path"] == "/sw.js"]
    assert not stray, f"a kitter tab fetched x.com's app: {stray}"
    x = js("""const d = document.documentElement.dataset;
        return [!!document.getElementById('react-root'), d.xBundle ?? null, d.sw ?? null]""")
    assert x == [False, None, None], f"x.com's page ran in a kitter tab (its root, bundle, service worker): {x}"
    background = js("return getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(48, 52, 70)", f"style.css did not apply: the page's background is {background}"
    tab = js("return [document.title, document.querySelector('link[rel=icon]')?.getAttribute('href')]")
    assert tab == ["Home / X", "/favicon.ico"], f"the tab's title and icon, as x.com's: {tab}"


def krusta_off() -> None:
    since = log_mark()
    go("https://x.com/home?krusta=off")
    worker = wait("document.documentElement.dataset.sw")
    x = js("return [!!document.getElementById('react-root'), document.documentElement.dataset.xBundle ?? null]")
    assert x == [True, "ran"], f"?krusta=off did not leave x.com's own page (its root, its bundle): {x}"
    paths = [r["path"] for r in requests(since)]
    assert worker == "refused" and "/sw.js" not in paths, f"x.com's service worker was {worker}; requests: {paths}"


def feed() -> None:
    since = log_mark()
    open_feed()
    shown = js(
        """const [a, part] = [arguments[0], (css) => a.querySelector(':scope > ' + css).textContent];
        return [part('.byline .name'), part('.byline'), part('.text'), part('.counts')]""",
        post(PLAIN),
    )
    text = "So on the platform today, I'm accused of being pro-Putin and also accused of fomenting revolution against Putin!"
    assert shown[0] == "Michael McFaul" and "@McFaul" in shown[1], f"byline: {shown[:2]}"
    assert shown[2].startswith(text + "\n\nAt least"), f"text: {shown[2]!r}"
    counts = re.findall(r"[\d.]+K?", shown[3])
    assert counts == ["17", "11", "152", "5.9K"], f"replies, reposts, likes, views: {counts} from {shown[3]!r}"
    calls = [r for r in requests(since) if r["path"].endswith("/HomeTimeline")]
    assert [r["status"] for r in calls[:1]] == [200], f"HomeTimeline answered {[r['status'] for r in calls]}"


def scroll() -> None:
    since = log_mark()
    open_feed()
    js("window.scrollTo(0, document.documentElement.scrollHeight)")
    # Page two's posts are page one's with every id's first digit made 9 (pages.py).
    wait("[...document.querySelectorAll('.byline a')].some((a) => /\\/status\\/9\\d{18}$/.test(a.href))")
    cursors = [r.get("cursor") for r in requests(since) if r["path"].endswith("/HomeTimeline")]
    assert cursors[:2] == [None, PAGE1_CURSOR], f"HomeTimeline's cursors: {cursors}"


def layouts() -> None:
    open_feed()
    for n in range(1, 5):
        boxes = js(
            """const grid = document.querySelector('.media.n' + arguments[0]);
            grid?.scrollIntoView({block: 'center'});
            return grid && [...grid.children].map((c) => {
              const r = c.getBoundingClientRect();
              return [Math.round(r.left), Math.round(r.top), Math.round(r.height)];
            })""",
            n,
        )
        assert boxes and len(boxes) == n, f"no .media.n{n} with {n} items: {boxes}"
        lefts, tops = {b[0] for b in boxes}, {b[1] for b in boxes}
        if n == 2:
            assert len(lefts) == 2 and len(tops) == 1, f"two side by side: {boxes}"
        if n == 3:
            (left, top, tall), (right, top2, short), (right2, low, _) = boxes
            shaped = top == top2 and tall > 1.8 * short and left < right == right2 and low > top2
            assert shaped, f"one tall and two stacked: {boxes}"
        if n == 4:
            assert len(lefts) == 2 and len(tops) == 2 and len({(b[0], b[1]) for b in boxes}) == 4, f"a square: {boxes}"


def viewer() -> None:
    open_feed()
    photo = browser.find_element(By.CSS_SELECTOR, ".media img")
    js("arguments[0].scrollIntoView({block: 'center'})", photo)
    since = log_mark()
    photo.click()
    src = wait("document.querySelector('.viewer img')?.getAttribute('src')")
    assert src.endswith("?name=large"), f"the viewer shows {src}"
    wait_request(since, lambda r: r["host"] == "pbs.twimg.com" and r["query"] == "name=large", "the large photo")
    ActionChains(browser).send_keys(Keys.ESCAPE).perform()
    wait("!document.querySelector('.viewer')", 5)


def video() -> None:
    since = log_mark()
    open_feed()
    clip = browser.find_element(By.CSS_SELECTOR, ".media video:not(.gif)")
    js("arguments[0].scrollIntoView({block: 'center'})", clip)
    time.sleep(2)  # what a preload would have fetched by now
    videos = [r["path"] for r in requests(since) if r["host"] == "video.twimg.com" and "/tweet_video/" not in r["path"]]
    assert not videos, f"videos fetched before any played: {videos}"
    clip.click()  # the reader's own click, which lets it play with sound
    js("arguments[0].play().catch(() => {})", clip)
    path = urlparse(clip.get_attribute("src")).path
    wait_request(since, lambda r: r["host"] == "video.twimg.com" and r["path"] == path, f"the video {path} once played")


def gif() -> None:
    open_feed()
    js("window.scrollTo(0, 0)")
    time.sleep(1)
    state = js("const v = document.querySelector('video.gif'); return [v.getBoundingClientRect().top > innerHeight, v.paused]")
    assert state == [True, True], f"the GIF off screen, paused: {state}"
    post(GIF)
    try:
        wait("(v => !v.paused && v.currentTime > 0.3)(document.querySelector('video.gif'))")
    except AssertionError as e:
        state = js("""const v = document.querySelector('video.gif');
            return {paused: v.paused, muted: v.muted, mutedAttribute: v.hasAttribute('muted'), readyState: v.readyState,
              networkState: v.networkState, error: v.error?.message ?? null}""")
        raise AssertionError(f"{e}; the GIF: {state}") from None
    js("window.scrollTo(0, 0)")
    wait("document.querySelector('video.gif').paused")


def text_links() -> None:
    open_feed()
    weiss = links(ENTITIES)
    assert weiss == [
        ["@kilmeade", "/kilmeade", ""],
        ["@FoxNews", "/FoxNews", ""],
        ["youtu.be/e9xHkOepUCs?t=…", "https://youtu.be/e9xHkOepUCs?t=2106", "_blank"],
    ], f"mentions and link: {weiss}"
    afp = links(HASHTAG)
    assert afp == [["#BREAKING", "/hashtag/BREAKING?krusta=off", ""]], f"hashtag: {afp}"
    shared = js("return arguments[0].querySelector(':scope > .text').textContent", post(GIF))
    assert shared == "kitter test: a GIF", f"a shared GIF's text, its media link cut: {shared!r}"
    # A mention of `/kitter.test` would link //kitter.test, and the link's address is `javascript:`: both stay text.
    hostile = [links(HOSTILE_LINKS), js("return arguments[0].querySelector(':scope > .text').textContent", post(HOSTILE_LINKS))]
    assert hostile == [[], HOSTILE_TEXT], f"a post's links off x.com: {hostile}"
    # A post by `/kitter.test` is left out: its author's link and its own page would both lead to //kitter.test.
    off = js(f"""return [...document.querySelectorAll('[href^="//"], [data-page^="//"], [data-page$="/{HOSTILE_AUTHOR}"]')]
        .map((e) => e.outerHTML.slice(0, 120))""")
    assert not off, f"a post by a handle X never allows, or a link off x.com: {off}"


def tabs() -> None:
    since = log_mark()
    open_feed()
    names = wait("(n => n.length > 2 && n)([...document.querySelectorAll('.tab')].map((b) => b.textContent))")
    assert names == ["For you", "Following", LIST_NAME, COMMUNITY_NAME], f"the tabs: {names}"
    js("document.querySelectorAll('.tab')[1].click()")
    wait("document.querySelector('article.post .byline a:last-of-type')?.href.includes('/status/8')")
    js("document.querySelectorAll('.tab')[2].click()")
    wait("/\\/status\\/2/.test(document.querySelector('article.post .byline a:last-of-type')?.href)")
    js("document.querySelectorAll('.tab')[3].click()")
    wait(f"document.querySelector('.byline a[href$=\"/status/{COMMUNITY_POST}\"]')")
    calls = [
        (r["operation"], r["method"], r["variables"].get("listId") or r["variables"].get("communityId"))
        for r in requests(since)
        if "operation" in r
    ]
    expected = [
        ("HomeLatestTimeline", "POST", None),
        ("ListLatestTweetsTimeline", "GET", LIST_ID),
        ("CommunityTweetsTimeline", "GET", COMMUNITY_ID),
    ]
    for call in expected:
        assert call in calls, f"no {call} among the calls: {calls}"


def profile() -> None:
    since = log_mark()
    go("https://x.com/XDevelopers")
    wait("document.querySelector('.profile h1')")
    shown = js("""const p = document.querySelector('.profile'), link = p.querySelector('.meta a');
        return [p.querySelector('h1').textContent, p.querySelector('.text').textContent, link?.textContent,
          link?.getAttribute('href'), [...p.querySelectorAll('.follows b')].map((b) => b.textContent)]""")
    bio = "The voice of the X Dev team and your official source for updates, news, and events, related to the X API."
    bio += " Ask @API, not dev@x.com."
    assert shown == ["Developers", bio, "docs.x.com", "https://docs.x.com/", ["770", "697.9K"]], f"the header: {shown}"
    # X marks no entity for a bio's @handle: kitter finds it, but not the one inside an address.
    mentions = js("return [...document.querySelectorAll('.profile .text a')].map((a) => [a.textContent, a.getAttribute('href')])")
    assert mentions == [["@API", "/API"]], f"the bio's mentions: {mentions}"
    title = js("return document.title")
    assert title == "Developers (@XDevelopers) / X", f"the profile's title: {title!r}"
    first = wait("document.querySelector('article.post .byline a:last-of-type')?.getAttribute('href')")
    assert first.endswith(f"/status/{PINNED}"), f"the first post's date links to {first}, not the pinned {PINNED}"
    mark = js("return document.querySelector('article.post .repost')?.textContent")
    assert mark == "📌 Pinned", f"the pinned post's mark: {mark!r}"
    calls = [(r["operation"], r["method"], r["variables"]) for r in requests(since) if "operation" in r]
    assert ("UserByScreenName", "GET", {"screen_name": "XDevelopers"}) in calls, f"the calls: {calls}"
    assert any(c[0] == "UserTweets" and c[2].get("userId") == "2244994945" for c in calls), f"the calls: {calls}"
    # x.com's own top-level pages are not handles: no profile is asked for.
    since = log_mark()
    go("https://x.com/settings")
    wait("document.querySelector('main.kitter p')")
    asked = [r["variables"] for r in requests(since) if r.get("operation") == "UserByScreenName"]
    assert not asked, f"/settings asked for a profile: {asked}"


def profile_tabs() -> None:
    go("https://x.com/XDevelopers")
    tabs = "[...document.querySelectorAll('.profile + .tabs .tab')]"
    names = wait(f"(n => n.length > 0 && n)({tabs}.map((b) => b.textContent))")
    assert names == ["Posts", "Replies", "Media"], f"the profile's tabs: {names}"
    since = log_mark()
    js(f"{tabs}[1].click()")
    wait(f"document.querySelector('.byline a[href$=\"/status/{REPLY}\"]')")
    js(f"{tabs}[2].click()")
    media = wait(
        "(p => p.length > 5 && p.map((a) => !!a.querySelector('.media')))([...document.querySelectorAll('article.post')])", 15
    )
    assert all(media), f"posts without media on the Media tab: {media.count(False)} of {len(media)}"
    calls = [(r["operation"], r["variables"].get("userId")) for r in requests(since) if "operation" in r]
    assert calls == [("UserTweetsAndReplies", "2244994945"), ("UserMedia", "2244994945")], f"the calls: {calls}"


def click_in_post(rest_id: str, part: str) -> str:
    """Clicks `part` of the feed's post `rest_id`, which is no link: the path of the page that opens."""
    open_feed()
    article = post(rest_id)
    go(lambda: js(f"arguments[0].querySelector('{part}').click()", article))
    return urlparse(browser.current_url).path


def post_page() -> None:
    since = log_mark()
    opened = click_in_post(PLAIN, ":scope > .text")
    assert opened == f"/McFaul/status/{PLAIN}", f"a click on a post's text opened {opened}"
    call = wait_request(since, lambda r: r.get("operation") == "TweetDetail", "TweetDetail")
    assert call["variables"].get("focalTweetId") == PLAIN, f"TweetDetail asked for {call['variables']}"
    open_feed()
    counts = js("return arguments[0].querySelector(':scope > .quote > .counts').textContent", post(QUOTING))
    found = re.findall(r"[\d.]+K?", counts)
    assert found == ["16", "160", "1.1K", "504.0K"], f"the quoted post's replies, reposts, likes, views: {counts!r}"
    opened = click_in_post(QUOTING, ":scope > .quote .byline")
    assert opened.endswith(f"/status/{QUOTED}"), f"a click in a quote opened {opened}, not the quoted post"
    opened = click_in_post(QUOTING, ":scope > .quote .byline img.avatar")
    assert opened == "/lrozen", f"a click on a quoted post's avatar opened {opened}, not its author's profile"
    go(f"https://x.com/XDevelopers/status/{DETAIL}")
    shown = wait(
        """(p => p.length > 10 && [p.length, p.findIndex((a) => a.classList.contains('focal')),
        p[0].querySelector('.byline .when').getAttribute('href')])([...document.querySelectorAll('article.post')])"""
    )
    assert shown[1:] == [0, f"/XDevelopers/status/{DETAIL}"], f"the post and its {shown[0] - 1} replies: {shown}"
    related = js(f"return document.querySelectorAll('article.post[data-page$=\"/{PLAIN}\"]').length")
    assert related == 0, "a post of X's Discover more, among the post's replies"
    title = js("return document.title")
    text = "Today, we are deprecating our Premium v1.1 API, including Premium Search and Account Activity API."
    assert title == f'Developers on X: "{text}" / X', f"the post's page's title: {title!r}"
    # The home tabs stay in the bar, none marked, and each opens the home page at itself.
    tabs = wait(
        """(t => t.length > 2 && t)
        ([...document.querySelectorAll('.bar .tab')].map((b) => [b.textContent, b.classList.contains('on')]))"""
    )
    assert tabs[:2] == [["For you", False], ["Following", False]], f"the bar of a post's page: {tabs}"
    go(
        lambda: js("[...document.querySelectorAll('.bar .tab')].find((b) => b.textContent === 'Following').click()"),
        "document.querySelector('.bar .tab.on')?.textContent === 'Following'",
    )
    where = js("return location.pathname + location.hash")
    assert where == "/home#following", f"Following on a post's page opened {where}"


# The posts of the recorded feed's first page whose next post answers them: the start of each reply chain but its last.
THREADED = {
    "2113000897756213353",
    "2113001580836380769",
    "2112994781513253007",
    "2112994887943733710",
    "2112992405590810671",
    "2112989837846343850",
}


def thread() -> None:
    """Reply chains joined by a line: a post the next one answers is marked and draws it, a post's page's own post
    too, into its author's thread below it."""
    open_feed()
    marked = js("return [...document.querySelectorAll('article.post.threaded')].map((a) => a.dataset.page.split('/').pop())")
    assert set(marked) == THREADED, f"the posts marked as a thread: {sorted(marked)}"
    wait(  # both parts of the line drawn: under the post's avatar, and above the next one's
        """(a => { a.scrollIntoView({block: 'center'});
        const height = (e, part) => parseFloat(getComputedStyle(e, part).height) || 0;
        const both = [height(a, '::after'), height(a.nextElementSibling, '::before')]; return both.every((h) => h > 0) && both; })
        (document.querySelector('article.post.threaded'))"""
    )
    go(f"https://x.com/XDevelopers/status/{DETAIL}")
    marked = wait(
        """(p => p.length > 10 && p.filter((a) => a.classList.contains('threaded')).map((a) => a.dataset.page.split('/').pop()))
        ([...document.querySelectorAll('article.post')])"""
    )
    assert marked == [DETAIL, "1649191521323995138", "1649191522485817345"], f"on the post's page, marked as a thread: {marked}"


def repost() -> None:
    """A repost's line names who reposted it as a byline does, with their avatar at two thirds of a post's, and the
    repost's own time, a day after the post's."""
    open_feed()
    shown = js(
        """const a = arguments[0], line = a.querySelector(':scope > .repost'), small = line?.querySelector('a.name > img.avatar');
        const width = (img) => img.getBoundingClientRect().width, avatar = a.querySelector(':scope > .author img');
        return [line?.textContent, small?.parentElement.getAttribute('href'),
          a.querySelector(':scope > .byline .when').textContent, small && width(small) / width(avatar)]""",
        post(SPANISH),
    )
    line, profile, posted, ratio = shown
    assert re.fullmatch(r"↻ toomas hendrik ilves @IlvesToomas reposted · Oct 21(, \d{4})?", line or ""), (
        f"the repost's line: {shown}"
    )
    assert profile == "/IlvesToomas" and posted.startswith("Oct 20") and 0.6 < ratio < 0.72, f"the repost's line: {shown}"
    go(lambda: js("arguments[0].querySelector(':scope > .repost img').click()", post(SPANISH)))
    assert urlparse(browser.current_url).path == "/IlvesToomas", f"the reposter's avatar opened {browser.current_url}"


def badges() -> None:
    """X's checks after a name, in its three colours, and an account's organisation, in the feed and on a profile."""
    since = log_mark()
    open_feed()
    shown = {
        rest_id: js(
            """const name = arguments[0].querySelector(':scope > .byline .name'), org = name.nextElementSibling;
            const shown = (a) => [a.getAttribute('href'), a.title, !!a.querySelector('img[src^="https://pbs"]')];
            return [name.dataset.badge ?? null, getComputedStyle(name, '::after').backgroundColor,
              org?.matches('a.affiliate') ? shown(org) : null]""",
            post(rest_id),
        )
        for rest_id in (GOLD, GREY, BLUE, ENTITIES)
    }
    expected = {
        GOLD: ["gold", "rgb(229, 200, 144)", ["/Polymarket", "Polymarket", True]],
        GREY: ["grey", "rgb(165, 173, 206)", ["/StateDept", "Department of State", True]],
        BLUE: ["blue", "rgb(133, 193, 220)", None],
        ENTITIES: [None, "rgba(0, 0, 0, 0)", None],
    }
    assert shown == expected, f"the badges of a gold, grey, blue and unbadged author: {shown}"
    language = [
        next((v for k, v in r["headers"].items() if k.lower() == "x-twitter-client-language"), None)
        for r in requests(since)
        if r.get("operation") == "HomeTimeline"
    ]
    assert language[:1] == ["uk"], f"HomeTimeline asked in {language}, not the account's language (its lang cookie)"
    go("https://x.com/XDevelopers")
    header = wait("""(h => h && [h.querySelector('[data-badge]')?.dataset.badge,
        h.querySelector('.affiliate')?.getAttribute('href')])(document.querySelector('.profile h1'))""")
    assert header == ["gold", "/X"], f"the profile's badge and organisation: {header}"


def translation() -> None:
    """A post X sent translated shows the translation first, as x.com does, with a button to the original and back."""
    open_feed()
    article = post(SPANISH)
    words = """const part = (css) => arguments[0].querySelector(':scope > ' + css)?.textContent;
        return [part('.translated'), part('.text')]"""
    shown = js(words, article)
    assert shown[0] == "Translated from Spanish · Show original", f"the translation's line: {shown}"
    assert "The United States and Italy have been" in shown[1], f"the post's words, translated: {shown}"
    js("arguments[0].querySelector(':scope > .translated button').click()", article)
    shown = js(words, article)
    assert shown[0].endswith("Show translation") and "Estados Unidos e Italia" in shown[1], f"after Show original: {shown}"
    js("arguments[0].querySelector(':scope > .translated button').click()", article)
    shown = js(words, article)
    assert shown[0].endswith("Show original") and "The United States" in shown[1], f"after Show translation: {shown}"
    # The translation's own entities: Ravid's post, translated, mentions @N12News.
    mention = js(
        "return [...arguments[0].querySelectorAll(':scope > .text a.mention')].map((a) => a.getAttribute('href'))", post(HEBREW)
    )
    assert mention == ["/N12News"], f"the Hebrew post's translated mentions: {mention}"


def load_more() -> None:
    """No button where X has nothing more: a post page past its replies, and a timeline past its end. X still sends a
    cursor for both, which pages only "Discover more" and empty pages."""
    since = log_mark()
    go(f"https://x.com/McFaul/status/{PLAIN}")
    wait("document.querySelector('article.post.focal')")
    time.sleep(1)
    shown = js("return [document.querySelectorAll('article.post').length, document.querySelector('.more')?.textContent ?? null]")
    asked = [r["cursor"] for r in requests(since) if r.get("operation") == "TweetDetail" and r.get("cursor")]
    assert shown == [1, None] and not asked, f"a post with no replies: {shown}, its later pages asked for: {asked}"
    open_feed()
    assert js("return document.querySelector('.more')?.textContent") == "Load more", "no button under a feed with more pages"
    js("document.querySelectorAll('.tab')[1].click()")
    wait("document.querySelector('article.post .byline a:last-of-type')?.href.includes('/status/8')")
    js("window.scrollTo(0, document.documentElement.scrollHeight)")
    wait("!document.querySelector('.more')")


NOT_SHARED = "kitter test: nothing shared yet"


def shared(article, part: str = ":scope > .counts .share", keyboard: bool = False) -> list:
    """What the share button `part` of `article` put on the clipboard, and the path the tab shows after. Clicked as a
    user clicks, or reached with Tab from the control before it and pressed with Enter. The clipboard is read in the
    browser's own window, so the test sees what it holds rather than what the page says it wrote."""
    chrome(f"Cc['@mozilla.org/widget/clipboardhelper;1'].getService(Ci.nsIClipboardHelper).copyString('{NOT_SHARED}')")
    button = js("const b = arguments[0].querySelector(arguments[1]); b.scrollIntoView({block: 'center'}); return b", article, part)
    if keyboard:
        js("const all = [...document.querySelectorAll('a[href], button')]; all[all.indexOf(arguments[0]) - 1].focus()", button)
        ActionChains(browser).send_keys(Keys.TAB).perform()
        assert js("return document.activeElement === arguments[0]", button), f"Tab did not reach the share button {part}"
        ActionChains(browser).send_keys(Keys.ENTER).perform()
    else:
        button.click()  # WebDriver's own click, a user's: Firefox lets a page write the clipboard only after one
    end = time.monotonic() + 8
    while (copied := chrome("return navigator.clipboard.readText()")) == NOT_SHARED and time.monotonic() < end:
        time.sleep(0.1)
    return [copied, js("return location.pathname")]


def share() -> None:
    """A post's share button copies its link on x.com, as the "Copy link" of X's share menu does, and a toast says so
    for a moment: in the feed, where a repost's link is the original's and a quote's the quoted post's, and on a post's
    page, for the post itself by keyboard and for a stranger's reply."""
    open_feed()
    shown = shared(post(PLAIN))
    assert shown == [f"https://x.com/McFaul/status/{PLAIN}", "/home"], f"a post's share button copied, then showed: {shown}"
    toast = wait("(t => t.textContent && [t.textContent, t.getAttribute('role')])(document.querySelector('.toast'))")
    assert toast == ["Copied to clipboard", "status"], f"the toast after a share, and its role: {toast}"
    wait("document.querySelector('.toast').textContent === ''")  # gone after 3 s
    copied = [shared(post(SPANISH))[0], shared(post(QUOTING), ":scope > .quote .share")[0]]
    expected = [f"https://x.com/UnamunoAgain/status/{SPANISH}", f"https://x.com/lrozen/status/{QUOTED}"]
    assert copied == expected, f"the links of a repost and of a quoted post: {copied}"
    go(f"https://x.com/XDevelopers/status/{DETAIL}")
    wait("document.querySelectorAll('article.post').length > 10")
    page = f"/XDevelopers/status/{DETAIL}"
    pairs = [shared(post(DETAIL), keyboard=True), shared(post(STRANGER))]
    wanted = [[f"https://x.com{page}", page], [f"https://x.com/AlSultan_Meriam/status/{STRANGER}", page]]
    assert pairs == wanted, f"on a post's page, the links of the post, by keyboard, and of a reply: {pairs}"


def chrome(script: str, *args):
    """`script` run in the browser's own window (WebDriver's chrome context), where the toolbar is; a promise it
    returns is awaited, as in the page."""
    browser.execute("SET_CONTEXT", {"context": "chrome"})
    try:
        return js(script, *args)
    finally:
        browser.execute("SET_CONTEXT", {"context": "content"})


# krusta's toolbar button: Firefox's own button inside the toolbar item it makes for the add-on.
BUTTON = 'document.querySelector("#krusta_kittyandrew-BAP, toolbarbutton#krusta_kittyandrew-browser-action")'


def toggle() -> None:
    open_feed()
    since = log_mark()
    browser.switch_to.window(browser.current_window_handle)  # the button acts on the selected tab
    go(lambda: chrome(f"{BUTTON}.click()"), "document.documentElement.dataset.sw")
    badge = chrome(f"return {BUTTON}.getAttribute('badge')")
    x = js("return [!!document.getElementById('react-root'), document.documentElement.dataset.xBundle ?? null]")
    assert [badge, *x] == ["off", True, "ran"], f"off did not reload into x.com's own page (badge, root, bundle): {badge, x}"
    go("https://x.com/settings")  # a new page stays x.com's
    worker = wait("document.documentElement.dataset.sw")
    paths = [r["path"] for r in requests(since)]
    assert js("return !!document.getElementById('react-root')"), f"kitter came back off; the page: {page_state()}"
    assert worker == "refused" and "/sw.js" not in paths, f"x.com's service worker was {worker}; requests: {paths}"
    go(lambda: chrome(f"{BUTTON}.click()"), "document.querySelector('main.kitter')")
    badge = chrome(f"return {BUTTON}.getAttribute('badge')")
    assert not badge, f"the badge still says {badge!r} with krusta on"


def in_content_script(code: str):
    """`code`'s value, a promise's awaited, run where krusta's content scripts run in the tab, as the add-on's own
    `scripting.executeScript` would: Firefox's ExtensionContent actor, which takes its parent's options."""
    return chrome(
        """const page = gBrowser.selectedBrowser.browsingContext.currentWindowGlobal;
        const options = {extensionId: 'krusta@kittyandrew', jsExecuteScriptSources: [{code: arguments[0]}], cssPaths: [],
          matches: ['https://x.com/*'], runAt: 'document_start', world: 'ISOLATED', wantReturnValue: true};
        return page.domProcess.getActor('ExtensionContent').sendQuery('Execute', {windows: [page.innerWindowId], options})
          .then((results) => results[0], (e) => 'failed: ' + (e.message ?? e));""",
        code,
    )


def api_only() -> None:
    """krustaFetch sends only a path under X's API, resolved: one off it would carry the client's CSRF header too."""
    go("https://x.com/settings")
    wait("document.querySelectorAll('.tab').length > 2")  # the page's own call, PinnedTimelines, answered
    since = log_mark()
    paths = ["/i/api/graphql/kitter-test/Nothing", "/i/api/1.1/account/settings.json", "/i/api/graphql/../1.1/kitter-test"]
    code = """Promise.all(%s.map((p) => Promise.resolve().then(() => krustaFetch(p, undefined, '{}'))
        .then((r) => r.status, (e) => e.message)))"""
    answers = in_content_script(code % json.dumps(paths))
    refused = [f"krustaFetch refuses {p}" for p in paths[1:]]
    sent = [r["path"] for r in requests(since) if r["path"].startswith("/i/api/")]
    assert answers == [404, *refused] and sent == [paths[0]], f"krustaFetch answered {answers}; the fake saw {sent}"


def api_error() -> None:
    browser.add_cookie({"name": "auth_token", "value": "expired", "path": "/", "secure": True, "httpOnly": True})
    try:
        go("https://x.com/home")
        # The feed's own error, just above its button: the pinned tabs' call fails too, and may show first.
        wait("document.querySelector('.more')?.previousElementSibling?.matches('.error')")
        error = js("return document.querySelector('.more').previousElementSibling.textContent")
        assert "HTTP 401" in error and "Could not authenticate you" in error, f"the error shown: {error}"
        button = wait("(t => t !== 'Loading…' && t)(document.querySelector('.more').textContent)")
        assert button == "Load more", f"the button after the error: {button}"
    finally:
        browser.add_cookie({"name": "auth_token", "value": SESSION, "path": "/", "secure": True, "httpOnly": True})


def sign_in_idle() -> None:
    """x.com's app in its own tab loads more scripts as it goes, after Firefox has stopped krusta's idle event page
    (2 s here, vm.nix): a sign-in page whose next step comes after the password is typed."""
    go("https://x.com/i/flow/login")
    wait("document.documentElement.dataset.xBundle")
    time.sleep(4)
    state = chrome("""return ChromeUtils.importESModule('resource://gre/modules/ExtensionParent.sys.mjs')
        .ExtensionParent.GlobalManager.getExtension('krusta@kittyandrew').backgroundState""")
    since = log_mark()
    js("""document.documentElement.dataset.xBundle = ''; const s = document.createElement('script');
        s.src = 'https://abs.twimg.com/responsive-web/client-web/main.test.js?step=2'; document.head.append(s)""")
    try:
        wait("document.documentElement.dataset.xBundle", 5)
    except AssertionError:
        asked = [r["query"] for r in requests(since) if r["host"] == "abs.twimg.com"]
        raise AssertionError(f"x.com's next script did not run, krusta's event page {state}; the fake saw {asked}") from None


def scroll_at_bottom() -> None:
    """The reader's wheel at the feed's end, two small steps 40 times."""
    js("window.scrollTo(0, document.documentElement.scrollHeight)")
    time.sleep(1)
    for _ in range(40):
        js("window.scrollBy(0, -3)")
        time.sleep(0.05)
        js("window.scrollBy(0, 3)")
        time.sleep(0.05)
    time.sleep(1)


def rate_limit() -> None:
    """The pinned list's second page answers 429 (fixture/server.py): kitter asks once, not again on every scroll."""
    open_feed()
    js("document.querySelectorAll('.tab')[2].click()")
    wait("/\\/status\\/2/.test(document.querySelector('article.post .byline a:last-of-type')?.href)")
    since = log_mark()
    scroll_at_bottom()
    calls = [r["status"] for r in requests(since) if r.get("operation") == "ListLatestTweetsTimeline"]
    assert calls == [429], f"the list's later pages while X answered 429: {calls}"


def timeline_end() -> None:
    """Following's later pages are empty but carry a bottom cursor, as X's are past the end: kitter stops at the first."""
    open_feed()
    js("document.querySelectorAll('.tab')[1].click()")
    wait("document.querySelector('article.post .byline a:last-of-type')?.href.includes('/status/8')")
    since = log_mark()
    scroll_at_bottom()
    calls = [r["cursor"] for r in requests(since) if r.get("operation") == "HomeLatestTimeline"]
    assert len(calls) == 1, f"{len(calls)} calls past Following's last post: {calls[:5]}"


def update() -> None:
    """krusta installed again over itself, as Zen's policy does when its build changes: an open kitter tab loads
    again and pages, where the old content script, which Firefox ends, left it drawn but dead."""
    open_feed()

    def reinstall() -> None:
        version = str(
            chrome("""const { AddonManager } = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
            return AddonManager.getInstallForURL('file:///run/krusta.xpi').then((i) => i.install())
              .then((a) => a.version, (e) => 'failed: ' + e);""")
        )
        assert not version.startswith("failed"), f"the reinstall: {version}"

    go(reinstall, "document.querySelectorAll('article.post').length > 50")
    since = log_mark()
    js("window.scrollTo(0, document.documentElement.scrollHeight)")
    wait_request(since, lambda r: r.get("operation") == "HomeTimeline" and r.get("cursor") == PAGE1_CURSOR, "page 2")


# Every scenario, in the order the clean run takes them; plants name them by these keys (vm.nix).
SCENARIOS: dict[str, Callable[[], None]] = {
    "takeover": takeover,
    "feed": feed,
    "links": text_links,
    "tabs": tabs,
    "profile": profile,
    "profile-tabs": profile_tabs,
    "post": post_page,
    "thread": thread,
    "repost": repost,
    "badges": badges,
    "translation": translation,
    "load-more": load_more,
    "share": share,
    "layouts": layouts,
    "viewer": viewer,
    "video": video,
    "gif": gif,
    "scroll": scroll,
    "krusta-off": krusta_off,
    "api-only": api_only,
    "api-error": api_error,
    "toggle": toggle,
    "sign-in-idle": sign_in_idle,
    "rate-limit": rate_limit,
    "timeline-end": timeline_end,
    "update": update,  # last: it installs krusta again
}


def session(label: str, names: list[str]) -> dict[str, str]:
    """A fresh Firefox with the build /run/krusta.xpi links to, through the named scenarios: what each failed with."""
    failed = {}
    try:
        start_browser()  # inside, so a start that fails still quits: else every later session finds this one open
        for name in names:
            try:
                with subtest(f"{label}: {name}"):
                    SCENARIOS[name]()
            except Exception:
                failed[name] = traceback.format_exc(limit=3).strip()
                print(f"{label}: {name} failed:\n{failed[name]}")
                browser.save_screenshot(str(OUT / f"failed-{label}-{name}.png"))
                (OUT / f"failed-{label}-{name}.html").write_text(browser.page_source)
    finally:
        browser.quit()
    return failed


def setup() -> None:
    global driver_port
    start_all()
    machine.wait_for_unit("fake-x.service")
    machine.wait_for_open_port(443)
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        driver_port = free.getsockname()[1]
    machine.succeed(f"systemctl start geckodriver@{driver_port}")
    machine.wait_for_open_port(driver_port)
    machine.send_monitor_command(f"hostfwd_add tcp:127.0.0.1:{driver_port}-:{driver_port}")  # the host's loopback to the VM


def run_feed(planted: str) -> None:
    """Every scenario on the clean build, then each plant's scenarios on its build, which must fail them all."""
    guarded("setup", setup)
    if not VERDICT:
        clean = session("clean", list(SCENARIOS))
        for name, why in clean.items():
            fail(f"scenario {name}: {why}")
        for plant, names in json.loads(planted).items():
            machine.succeed(f"ln -sfn $(readlink /run/krusta-plants/{plant}.xpi) /run/krusta.xpi")
            caught: dict[str, str] = {}
            guarded(f"plant {plant}", lambda: caught.update(session(plant, names)))
            for name in names:
                verdict = caught[name].splitlines()[-1] if name in caught else "MISSED"
                print(f"plant {plant:18} {name:10} {verdict}")
                if name in clean:
                    fail(f"planted bug {plant}: scenario {name} fails on the clean build too, which proves nothing")
                elif name not in caught:
                    fail(f"planted bug {plant} not caught by scenario {name}")
    collect(machine, LOG, "/var/log/firefox")
    record()
