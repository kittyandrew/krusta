"""The fake X's timeline answers, derived from one recorded timeline: twscrape's list timeline, which has
HomeTimeline's instructions, entries and tweets under another key.

- page1.json: the recording, with two posts added for media it lacks: three photos (a copy of a four-photo post
  less one) at the top, and a GIF (a copy of a video post) far enough down to start off screen. The GIF is shared
  from another post, so X leaves its media link inside the display range. Below the photos, two hostile posts X
  would never send: one whose mention's handle and link's address lead off x.com (`//kitter.test`, `javascript:`),
  and one by an account with such a handle.
- page2.json: page 1's recorded posts again with every post id's first digit made 9, behind page 1's bottom cursor,
  so its posts are new to the client. Its own bottom cursor is END_CURSOR.
- following.json: the same with 8 for the Following tab, so a scenario tells it from For You.
- list.json: the recording itself, which is a list's timeline: the pinned list's posts.
- pinned.json: the account's pinned timelines, the list LIST_ID and the community COMMUNITY_ID, whose posts are
  twscrape's recorded community (default.nix).
- end.json: no posts and no cursor, the answer for END_CURSOR or any cursor the fake does not know.
- past-end.json: no posts but a bottom cursor, as X answers past a timeline's last post: Following's later pages.

usage: pages.py <recorded.json> <out dir>
"""

import copy
import json
import sys
from pathlib import Path

THREE_PHOTOS = "1000000000000000003"  # the scenarios find the added posts by these ids
GIF = "1000000000000000004"
GIF_AT = 15  # entries above it: about 15 posts down, well below a 900 px window
GIF_TEXT = "kitter test: a GIF"
GIF_LINK = "https://t.co/KitterTest"
HOSTILE_LINKS, HOSTILE_AUTHOR = "1000000000000000005", "1000000000000000006"
HOSTILE_HANDLE = "/kitter.test"  # `/<handle>` would be //kitter.test, another site
HOSTILE_MENTION, HOSTILE_LINK = f"@{HOSTILE_HANDLE}", "https://t.co/KitterJs"
HOSTILE_TEXT = f"kitter test: {HOSTILE_MENTION} {HOSTILE_LINK}"
END_CURSOR = "kitter-test-end"
# server.py and the scenarios name these too.
LIST_ID, LIST_NAME = "1000000000000000099", "kitter test list"
COMMUNITY_ID, COMMUNITY_NAME = "1000000000000000098", "kitter test community"


def tweets(value):
    """Every tweet object anywhere in `value`: entries, conversations, quotes and reposts' originals."""
    if isinstance(value, dict):
        if value.get("__typename") == "Tweet" and "legacy" in value:
            yield value
        for child in value.values():
            yield from tweets(child)
    elif isinstance(value, list):
        for child in value:
            yield from tweets(child)


def first(entries, test):
    return next(copy.deepcopy(t) for t in tweets(entries) if test(t))


def media_types(tweet) -> list[str]:
    return [m["type"] for m in tweet["legacy"].get("extended_entities", {}).get("media", [])]


def added(template, tweet, rest_id: str, text: str):
    """`tweet` as a post of its own with this id and text, in an entry shaped like `template`."""
    tweet["rest_id"] = tweet["legacy"]["id_str"] = rest_id
    tweet["legacy"]["full_text"] = text
    tweet["legacy"]["display_text_range"] = [0, len(text)]
    tweet["legacy"]["entities"] = {"hashtags": [], "symbols": [], "urls": [], "user_mentions": []}
    for key in ("quoted_status_result", "note_tweet"):
        tweet.pop(key, None)
    tweet["legacy"].pop("retweeted_status_result", None)
    entry = copy.deepcopy(template)
    entry["entryId"] = f"tweet-{rest_id}"
    entry["content"]["itemContent"]["tweet_results"]["result"] = tweet
    return entry


def span(text: str, part: str) -> list[int]:
    """`part`'s indices in `text`, as X marks an entity."""
    return [text.index(part), text.index(part) + len(part)]


def home(instructions) -> str:
    return json.dumps({"data": {"home": {"home_timeline_urt": {"instructions": instructions}}}})


def main() -> None:
    recorded = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    entries = recorded["data"]["list"]["tweets_timeline"]["timeline"]["instructions"][0]["entries"]
    template = next(e for e in entries if e["content"]["entryType"] == "TimelineTimelineItem")

    three = first(entries, lambda t: media_types(t) == ["photo"] * 4)
    three["legacy"]["extended_entities"]["media"].pop()
    gif = first(entries, lambda t: media_types(t) == ["video"])
    clip = gif["legacy"]["extended_entities"]["media"][0]
    # As X sends a GIF: one MP4 at bitrate 0 under tweet_video, its still under tweet_video_thumb.
    clip["type"] = "animated_gif"
    clip["media_url_https"] = "https://pbs.twimg.com/tweet_video_thumb/KitterTestGif.jpg"
    clip["video_info"]["variants"] = [
        {"bitrate": 0, "content_type": "video/mp4", "url": "https://video.twimg.com/tweet_video/KitterTestGif.mp4"}
    ]
    page1 = copy.deepcopy(entries)
    page1.insert(GIF_AT, added(template, gif, GIF, f"{GIF_TEXT} {GIF_LINK}"))
    gif["legacy"]["entities"]["media"] = [{"url": GIF_LINK, "indices": [len(GIF_TEXT) + 1, len(GIF_TEXT) + 1 + len(GIF_LINK)]}]
    plain = first(entries, lambda t: not media_types(t) and not t["legacy"].get("in_reply_to_status_id_str"))
    links, author = copy.deepcopy(plain), copy.deepcopy(plain)
    page1[0:0] = [
        added(template, three, THREE_PHOTOS, "kitter test: three photos"),
        added(template, links, HOSTILE_LINKS, HOSTILE_TEXT),
        added(template, author, HOSTILE_AUTHOR, "kitter test: by a handle X never allows"),
    ]
    mention = {"screen_name": HOSTILE_HANDLE, "indices": span(HOSTILE_TEXT, HOSTILE_MENTION)}
    script = {"url": HOSTILE_LINK, "expanded_url": "javascript:document.title='hijacked'", "display_url": "kitter.test"}
    links["legacy"]["entities"] |= {"user_mentions": [mention], "urls": [script | {"indices": span(HOSTILE_TEXT, HOSTILE_LINK)}]}
    author["core"]["user_results"]["result"]["core"]["screen_name"] = HOSTILE_HANDLE
    (out / "page1.json").write_text(home([{"type": "TimelineAddEntries", "entries": page1}]))

    for name, digit in (("page2", "9"), ("following", "8")):
        renumbered = copy.deepcopy(entries)
        for tweet in tweets(renumbered):
            tweet["rest_id"] = tweet["legacy"]["id_str"] = digit + tweet["rest_id"][1:]
        for entry in renumbered:
            if entry["content"].get("cursorType") == "Bottom":
                entry["content"]["value"] = END_CURSOR
        (out / f"{name}.json").write_text(home([{"type": "TimelineAddEntries", "entries": renumbered}]))
    (out / "end.json").write_text(home([{"type": "TimelineAddEntries", "entries": []}]))
    past = {
        "entryId": "cursor-bottom-0",
        "content": {"entryType": "TimelineTimelineCursor", "cursorType": "Bottom", "value": "past"},
    }
    (out / "past-end.json").write_text(home([{"type": "TimelineAddEntries", "entries": [past]}]))
    (out / "list.json").write_text(json.dumps(recorded))
    pinned = [
        {"__typename": "ListPinnedTimeline", "list": {"id_str": LIST_ID, "name": LIST_NAME}},
        {
            "__typename": "CommunityPinnedTimeline",
            "community_results": {"result": {"id_str": COMMUNITY_ID, "name": COMMUNITY_NAME}},
        },
        {"__typename": "TopicPinnedTimeline", "topic": {"name": "kitter leaves topics out"}},
    ]
    (out / "pinned.json").write_text(json.dumps({"data": {"pinned_timelines": {"pinned_timelines": pinned}}}))
    bottom = next(e["content"]["value"] for e in entries if e["content"].get("cursorType") == "Bottom")
    (out / "page1-cursor").write_text(bottom)


main()
