"""The fake X the VM tests run against: x.com, abs.twimg.com, pbs.twimg.com and video.twimg.com over TLS on
127.0.0.1:443, where /etc/hosts sends those names (default.nix). Every request is a JSON line in the access log, so
a test proves what a page never asked for.

- x.com: any page is X's own (PAGE), which runs a bundle from abs.twimg.com and registers the service worker
  /sw.js. The API, /i/api/graphql/<queryId>/<operation>, answers only the query ids and feature switch names in
  graphql.json, the two home timelines as POSTs and the rest as GETs, and only with the web bearer, the session
  cookie and an `x-csrf-token` equal to the `ct0` cookie; else an error shaped as X's. Answers (pages.py):
  - HomeTimeline: page 1, page 2 for page 1's bottom cursor, the end for any other cursor.
  - HomeLatestTimeline: one page, then empty pages with a bottom cursor, as X answers past a timeline's end.
  - ListLatestTweetsTimeline (for LIST_ID): one page, then X's rate limit (429) for any later one.
  - CommunityTweetsTimeline (for COMMUNITY_ID) and UserTweets, UserTweetsAndReplies and UserMedia (for USER_ID):
    one page, then the end.
  - UserByScreenName: @XDevelopers, and no user for any other handle. PinnedTimelines: pinned.json.
  - TweetDetail: POST_ID's page with its replies, and an empty one for any other post.
- abs.twimg.com: the bundle, which marks the page it ran in.
- pbs.twimg.com: an image for `?name=small` or `?name=large`, avatars and banners; nothing at other sizes.
- video.twimg.com: an MP4 for any .mp4 path, with byte ranges as media elements ask.

usage: server.py <data dir> <tls dir> <graphql.json> <access log>
"""

import json
import re
import ssl
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

DATA, CERTS, SPEC, LOG = (Path(a) for a in sys.argv[1:5])
OPERATIONS = json.loads(SPEC.read_text())
PAGE1_CURSOR = (DATA / "page1-cursor").read_text()
LIST_ID, COMMUNITY_ID = "1000000000000000099", "1000000000000000098"  # pages.py's pinned tabs
USER_ID, HANDLE = "2244994945", "xdevelopers"  # the recorded profile's
POST_ID = "1649191520250245121"  # the recorded post page's post, by @XDevelopers
# x.com's public web bearer, the one kitter_api::BEARER sends.
BEARER = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
SESSION = "kitter-test-session"  # the auth_token cookie the scenarios seed (sites/kitter/tests/scenarios.py)
BUNDLE = "https://abs.twimg.com/responsive-web/client-web/main.test.js"
# What reaches the page of X's own app: its bundle, and its service worker's registration, whose outcome lands in
# `data-sw` for the scenarios to read.
PAGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>X</title><script src="{BUNDLE}"></script></head>
<body><div id="react-root"></div><script>
navigator.serviceWorker.register("/sw.js").then(
  () => (document.documentElement.dataset.sw = "registered"),
  () => (document.documentElement.dataset.sw = "refused"))
</script></body></html>""".encode()
# A strict policy, as x.com sends one; krusta's background.js drops it in a krusta tab.
CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://abs.twimg.com; style-src 'self' 'unsafe-inline'"
    " https://abs.twimg.com; img-src 'self' https://pbs.twimg.com; media-src https://video.twimg.com; connect-src 'self'"
)
# X's service worker caches the app and answers from that cache, past the network.
WORKER = f"""self.addEventListener("install", (e) => e.waitUntil(caches.open("x").then((c) => c.addAll(["/home", "{BUNDLE}"]))))
self.addEventListener("fetch", (e) => e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request))))
""".encode()
BUNDLE_JS = b'document.documentElement.dataset.xBundle = "ran"\n'
UNAUTHORIZED = (401, {"errors": [{"code": 32, "message": "Could not authenticate you."}]})
BAD_TOKEN = (401, {"errors": [{"code": 89, "message": "Invalid or expired token."}]})
CSRF = (403, {"errors": [{"code": 353, "message": "This request requires a matching csrf cookie and header."}]})
RATE_LIMITED = (429, {"errors": [{"code": 88, "message": "Rate limit exceeded."}]})
NOT_FOUND = {"errors": [{"message": "Query: Unspecified"}]}  # an unknown query id, or a call sent by the wrong method
NO_USER = b'{"data": {"user": {}}}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: one connection carries a page's many requests

    def setup(self):
        # TLS in the connection's own thread: a client that connects and stalls would hold accept() otherwise.
        self.request = TLS.wrap_socket(self.request, server_side=True)
        super().setup()

    def log_message(self, format, *args):
        pass  # the access log below holds every request

    def do_GET(self):
        self.route(None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.route(self.rfile.read(length))

    def route(self, body: bytes | None) -> None:
        host = (self.headers.get("Host") or "").split(":")[0]
        path, _, query = self.path.partition("?")
        entry = {"t": time.time(), "host": host, "method": self.command, "path": path, "query": query}
        entry["headers"] = dict(self.headers)
        if host == "x.com" and (call := re.fullmatch(r"/i/api/graphql/([\w-]+)/(\w+)", path)):
            status, kind, data = self.api(call[1], call[2], body, query, entry)
        elif host == "x.com" and path == "/sw.js":
            status, kind, data = 200, "text/javascript", WORKER
        elif host == "x.com" and body is None and not path.startswith("/i/api/"):
            status, kind, data = 200, "text/html; charset=utf-8", PAGE
        elif host == "abs.twimg.com" and path == BUNDLE.removeprefix("https://abs.twimg.com"):
            status, kind, data = 200, "text/javascript", BUNDLE_JS
        elif host == "pbs.twimg.com" and (re.search(r"(^|&)name=(small|large)(&|$)", query) or "/profile_" in path):
            size = "large" if "name=large" in query else "avatar" if "/profile_images/" in path else "small"
            status, kind, data = 200, "image/jpeg", (DATA / f"{size}.jpg").read_bytes()
        elif host == "video.twimg.com" and path.endswith(".mp4"):
            return self.video(entry)
        else:
            status, kind, data = 404, "text/plain", b"not in the fake X\n"
        self.answer(entry, status, kind, data, {"Content-Security-Policy": CSP} if kind.startswith("text/html") else {})

    def api(self, query_id: str, operation: str, body: bytes | None, query: str, entry: dict) -> tuple[int, str, bytes]:
        spec = OPERATIONS.get(operation, {})
        if query_id != spec.get("queryId") or (body is not None) != operation.startswith("Home"):
            return 404, "application/json", json.dumps(NOT_FOUND).encode()
        sent = json.loads(body) if body is not None else {k: json.loads(v[0]) for k, v in parse_qs(query).items()}
        variables = entry["variables"] = sent.get("variables", {})
        cursor = entry["cursor"] = variables.get("cursor")
        entry["operation"] = operation
        cookies = {k: v.value for k, v in SimpleCookie(self.headers.get("Cookie") or "").items()}
        if self.headers.get("Authorization") != BEARER:
            status, error = BAD_TOKEN
        elif cookies.get("auth_token") != SESSION:
            status, error = UNAUTHORIZED
        elif not cookies.get("ct0") or self.headers.get("x-csrf-token") != cookies["ct0"]:
            status, error = CSRF
        elif missing := sorted(set(spec.get("features", OPERATIONS["features"])) - set(sent.get("features", {}))):
            status, error = 400, {"errors": [{"code": 336, "message": f"The following features cannot be null: {missing}"}]}
        elif operation == "ListLatestTweetsTimeline" and cursor is not None:
            status, error = RATE_LIMITED
        else:
            page = entry["page"] = self.page(operation, variables, cursor)
            return 200, "application/json", (DATA / f"{page}.json").read_bytes() if page else NO_USER
        return status, "application/json", json.dumps(error).encode()

    @staticmethod
    def page(operation: str, variables: dict, cursor: str | None) -> str | None:
        """The pages.py answer for a call, or None for a handle with no account."""
        if operation == "UserByScreenName":
            return "user" if str(variables.get("screen_name")).lower() == HANDLE else None
        if cursor is not None:
            if operation == "HomeLatestTimeline":
                return "past-end"
            return "page2" if operation == "HomeTimeline" and cursor == PAGE1_CURSOR else "end"
        return {
            "HomeTimeline": "page1",
            "HomeLatestTimeline": "following",
            "PinnedTimelines": "pinned",
            "ListLatestTweetsTimeline": "list" if variables.get("listId") == LIST_ID else "end",
            "CommunityTweetsTimeline": "community" if variables.get("communityId") == COMMUNITY_ID else "end",
            "UserTweets": "user-tweets" if variables.get("userId") == USER_ID else "end",
            "UserTweetsAndReplies": "user-replies" if variables.get("userId") == USER_ID else "end",
            "UserMedia": "user-media" if variables.get("userId") == USER_ID else "end",
            "TweetDetail": "post" if variables.get("focalTweetId") == POST_ID else "end",
        }[operation]

    def video(self, entry: dict) -> None:
        data = (DATA / "video.mp4").read_bytes()
        wanted = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if not wanted:
            return self.answer(entry, 200, "video/mp4", data, {"Accept-Ranges": "bytes"})
        start, end = int(wanted[1]), int(wanted[2] or len(data) - 1)
        part = data[start : end + 1]
        self.answer(entry, 206, "video/mp4", part, {"Content-Range": f"bytes {start}-{start + len(part) - 1}/{len(data)}"})

    def answer(self, entry: dict, status: int, kind: str, data: bytes, headers: dict) -> None:
        entry["status"] = status
        with LOG.open("ab", buffering=0) as log:  # one write() a line: buffered, a long one went out in parts
            log.write((json.dumps(entry) + "\n").encode())
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


TLS = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
TLS.load_cert_chain(CERTS / "server.pem", CERTS / "server.key")
ThreadingHTTPServer(("127.0.0.1", 443), Handler).serve_forever()
