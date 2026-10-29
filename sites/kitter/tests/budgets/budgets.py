"""DEVELOPMENT ONLY, run by run.sh beside it: kitter's speed measurements (docs/design.md, Speed measurements) in a
real headless Firefox on this machine, with kitter installed, against a fake x.com that serves a recorded timeline.
Never a flake check: kubicle measured every step two to five times slower in a VM.

usage: budgets.py EXTENSION_DIR TIMELINE_JSON TLS_DIR

run.sh starts it in a network namespace of its own, where it may listen on port 443 and nothing reaches the real
x.com: Firefox resolves x.com and twimg.com to 127.0.0.1 (`network.dns.localDomains`) and takes the fake's
certificate, vm-kitter's test one (TLS_DIR), from a CA it does not know (`acceptInsecureCerts`). Page n of the For You
feed is the recording with every post id suffixed by n, so the pages never share a post, and a bottom cursor that names
page n + 1.

Each measurement prints its median over several runs beside the last run's, kept in LAST: numbers to compare across a
change, never a limit that fails the run."""

import functools
import json
import shutil
import ssl
import struct
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.firefox.service import Service

EXTENSION, TIMELINE, TLS = sys.argv[1:4]
PROBE = Path(__file__).parent / "probe"  # marks the first post's time (probe/probe.js)
HOSTS = ["x.com", "pbs.twimg.com", "video.twimg.com", "abs.twimg.com"]
PAGES = 5  # the feed paged this far for the scroll, heap and DOM measurements: about 470 posts
STEP = 80  # pixels scrolled per frame: 4,800 px/s at 60 frames a second, a quick flick through the feed
# How long X takes to answer a next page, which the prefetch must hide. Assumed from the bench (../bench): in
# Andrew's Zen, kitter's first post came 1.2 s or more after navigation, mostly X's answer (Oct 27, 2026).
LATENCY = 1.0
LAST = Path.home() / ".local/state/krusta/kitter-speed.json"  # each measurement's median from the run before
last = json.loads(LAST.read_text()) if LAST.exists() else {}
medians: dict[str, float] = {}


def png(width: int, height: int) -> bytes:
    """A gradient, so each image Firefox decodes is a real one and not a 1 px stand-in."""
    rows = b"".join(
        b"\0" + bytes(c for x in range(width) for c in (x * 255 // width, y * 255 // height, 128)) for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


IMAGE = png(400, 225)  # every avatar, photo and video still; X's `small` photos are up to 680 px wide


@functools.cache
def page(n: int) -> bytes:
    root = json.loads(Path(TIMELINE).read_text())

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("__typename") == "Tweet":
                value["rest_id"] += f"{n:03}"
            if value.get("cursorType") == "Bottom":
                value["value"] = f"budget-page-{n + 1}"
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(root)
    return json.dumps(root).encode()


class FakeX(BaseHTTPRequestHandler):
    """x.com's page (any HTML: kitter replaces it), HomeTimeline's pages, and one image for every twimg.com path."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def answer(self, status: int, kind: str, body: bytes, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        match self.headers["Host"]:
            case "x.com" if self.path.startswith("/i/api/"):  # PinnedTimelines: an account with no pinned tabs
                self.answer(200, "application/json", b'{"data": {}}')
            case "x.com":  # ct0 stands for the signed-in session: kitter sends it back as x-csrf-token
                self.answer(200, "text/html", b"<!doctype html><title>X</title>", "ct0=budget; Path=/; Secure; SameSite=Lax")
            case "pbs.twimg.com":
                self.answer(200, "image/png", IMAGE)
            case _:
                self.answer(404, "text/plain", b"")

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers["Host"] != "x.com" or not self.path.endswith("/HomeTimeline"):
            return self.answer(404, "text/plain", b"")
        cursor = body["variables"].get("cursor")
        if cursor:
            time.sleep(LATENCY)
        self.answer(200, "application/json", page(int(cursor.removeprefix("budget-page-")) if cursor else 0))


def serve() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 443), FakeX)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(f"{TLS}/server.pem", f"{TLS}/server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def measured(name: str, values: list[float], unit: str) -> None:
    took = medians[name] = sorted(values)[len(values) // 2]
    before = f"last {last[name]:9.1f}" if name in last else f"last {'-':>9}"
    print(f"{name:40} median {took:9.1f} {unit:5} {before} {unit:5} {[round(v, 1) for v in values]}")


def open_feed() -> float:
    """A fresh navigation to the feed; the milliseconds from its start until the first post is laid out."""
    # get() returns at once (the "none" strategy below); the old document's mark keeps its own post from counting.
    driver.execute_script("document.documentElement.dataset.left = ''")
    driver.get("https://x.com/home")
    end = time.monotonic() + 10
    while time.monotonic() < end:
        try:
            mark = driver.execute_script("const d = document.documentElement.dataset; return d.left === undefined && d.firstPost")
        except WebDriverException:
            mark = None  # the navigation in progress
        if mark:
            return float(mark)
        time.sleep(0.02)
    raise AssertionError("no post within 10 s: " + driver.execute_script("return document.body.innerText.slice(0, 300)"))


def first_posts() -> None:
    measured("navigation to the first posts", [open_feed() for _ in range(5)], "ms")


# Scrolls STEP px each frame until PAGES pages are in, timing each frame by requestAnimationFrame's clock. Headless
# Firefox draws every 17.06 ms; a frame that took two such periods is one the main thread was too busy to draw on
# time. `stalled` counts frames at the end of the feed, waiting for the next page, which should start loading six
# screens before it (docs/design.md, Speed).
SCROLL = """
const [pages, step, done] = arguments;
const posts = document.getElementsByClassName('post'), perPage = posts.length, frames = [], t0 = performance.now();
let last = null, stalled = 0;
const frame = now => {
  if (last !== null) frames.push(now - last);
  last = now;
  const before = scrollY;
  scrollBy(0, step);
  if (scrollY === before) stalled++;
  if (posts.length >= pages * perPage || now - t0 > 120000) return done({frames, stalled, posts: posts.length, perPage});
  requestAnimationFrame(frame);
};
requestAnimationFrame(frame);
"""

# The tab's JS heap: every JS memory report of x.com's content process (Firefox puts each site in its own), the
# client's wasm memory and the content scripts included. Read after a full GC, so what is left is what the page holds.
HEAP = """
const done = arguments[0];
const reporter = Cc["@mozilla.org/memory-reporter-manager;1"].getService(Ci.nsIMemoryReporterManager);
reporter.minimizeMemoryUsage(() => {
  let js = 0;
  reporter.getReports((process, path, kind, units, amount) => {
    if (process.startsWith('webIsolated=https://x.com ') && path.startsWith('js-main-runtime/')) js += amount;
  }, null, () => done(js), null, false);
});
"""


def paging() -> None:
    worst, dropped, stalled, heap, nodes = [], [], [], [], []
    for _ in range(3):
        open_feed()
        run = driver.execute_async_script(SCROLL, PAGES, STEP)
        assert run["posts"] >= PAGES * run["perPage"], f"{run['posts']} posts after 120 s, not {PAGES} pages"
        period = sorted(run["frames"])[len(run["frames"]) // 2]  # the refresh rate, as nearly every frame is on time
        worst.append(max(run["frames"]))
        dropped.append(sum(max(0, round(f / period) - 1) for f in run["frames"]))
        stalled.append(run["stalled"])
        nodes.append(driver.execute_script("return document.getElementsByTagName('*').length"))
        driver.set_context("chrome")
        heap.append(driver.execute_async_script(HEAP) / 2**20)
        driver.set_context("content")
    measured(f"worst frame while paging {PAGES} pages", worst, "ms")
    measured(f"frames dropped while paging {PAGES} pages", dropped, "")
    measured("frames stalled at the feed's end", stalled, "")
    measured(f"JS heap after {PAGES} pages", heap, "MB")
    measured(f"DOM nodes after {PAGES} pages", nodes, "")


def size() -> None:
    """What the tab loads from the add-on before the first post: X's client's wasm, then its JS glue, sites.js and
    content.js, and the stylesheet. One measurement each, since the build is deterministic."""
    files = Path(EXTENSION)
    measured("wasm loaded", [(files / "sites/kitter/client_bg.wasm").stat().st_size / 1024], "KB")
    js = ["sites/kitter/client.js", "sites.js", "content.js", "sites/kitter/style.css"]
    measured("JS and CSS loaded", [sum((files / f).stat().st_size for f in js) / 1024], "KB")


server = serve()
options = webdriver.FirefoxOptions()
options.add_argument("-headless")
options.accept_insecure_certs = True
# A kitter page never finishes loading for WebDriver (content.js stops x.com's page): get() must not wait for it.
options.page_load_strategy = "none"
options.binary_location = shutil.which("firefox") or "firefox"
options.set_preference("network.dns.localDomains", ",".join(HOSTS))
# --allow-system-access: HEAP reads Firefox's memory reports, which only the browser's own chrome context can.
driver = webdriver.Firefox(options=options, service=Service(shutil.which("geckodriver"), service_args=["--allow-system-access"]))
try:
    driver.set_window_size(1280, 900)
    driver.set_script_timeout(180)
    driver.install_addon(EXTENSION, temporary=True)
    driver.install_addon(str(PROBE), temporary=True)
    size()
    first_posts()
    paging()
finally:
    driver.quit()
    server.shutdown()
LAST.parent.mkdir(parents=True, exist_ok=True)
LAST.write_text(json.dumps(medians, indent=1) + "\n")
print(f"kept in {LAST}")
