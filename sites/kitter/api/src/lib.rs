//! X's web API as x.com's own app calls it: the timelines, a post's page, profiles and pinned lists, and their
//! answers parsed. Answers are walked as JSON rather than decoded into fixed structs, since X adds and moves
//! fields often and a post missing an optional part should still show.

use std::{fmt::Write, sync::LazyLock};

use serde_json::{Value, json};

/// The public bearer token every x.com page sends with its own API calls; the session is in the cookies.
pub const BEARER: &str = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA";

/// Each call's query id, feature switches and field toggles, as x.com's bundle sent them
/// (fa0311/TwitterInternalAPIDocument, Oct 27, 2026). A missing switch fails the call with error 336. The timeline
/// calls share the top-level switches and toggles; a call with its own names them.
static GRAPHQL: LazyLock<Value> = LazyLock::new(|| serde_json::from_str(include_str!("graphql.json")).expect("graphql.json is valid JSON"));

/// An API call for the page to send, by its path on the site: `body` is set for a POST, else it is a GET with
/// everything in the path's query.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Request {
    pub path: String,
    pub body: Option<String>,
}

/// A list of posts kitter shows, in the order X sends them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Timeline {
    ForYou,
    Following,
    /// A list's id.
    List(String),
    /// A community's id, its posts in the community's own Top order.
    Community(String),
    /// A user's id (`rest_id`), not their handle: their posts, as their profile's Posts tab shows them.
    User(String),
    /// A user's id: their posts and replies, the profile's Replies tab.
    Replies(String),
    /// A user's id: their posts with photos or videos, the profile's Media tab.
    Media(String),
    /// A post's id: the thread it answers, the post, then its replies.
    Post(String),
}

/// One page of a timeline. `cursor` is the previous page's `next`.
#[must_use]
pub fn timeline(which: &Timeline, cursor: Option<&str>) -> Request {
    let home = json!({"count": 20, "includePromotedContent": false, "latestControlAvailable": true, "requestContext": "launch", "withCommunity": true, "seenTweetIds": []});
    let (operation, mut variables) = match which {
        Timeline::ForYou => ("HomeTimeline", home),
        Timeline::Following => ("HomeLatestTimeline", home),
        Timeline::List(id) => ("ListLatestTweetsTimeline", json!({"listId": id, "count": 20})),
        Timeline::Community(id) => (
            "CommunityTweetsTimeline",
            json!({"communityId": id, "count": 20, "displayLocation": "Community", "rankingMode": "Relevance", "withCommunity": true}),
        ),
        Timeline::User(id) => ("UserTweets", json!({"userId": id, "count": 20, "includePromotedContent": false, "withVoice": true})),
        Timeline::Replies(id) => (
            "UserTweetsAndReplies",
            json!({"userId": id, "count": 20, "includePromotedContent": false, "withCommunity": true, "withVoice": true}),
        ),
        Timeline::Media(id) => ("UserMedia", json!({"userId": id, "count": 20, "includePromotedContent": false, "withVoice": true})),
        Timeline::Post(id) => (
            "TweetDetail",
            // Every one x.com's app sends: X answers 422 when one is missing, `withBirdwatchNotes` here (Oct 28, 2026).
            json!({"focalTweetId": id, "with_rux_injections": false, "rankingMode": "Relevance", "includePromotedContent": false,
                "withCommunity": true, "withQuickPromoteEligibilityTweetFields": false, "withBirdwatchNotes": true, "withVoice": true}),
        ),
    };
    if let Some(cursor) = cursor {
        variables["cursor"] = cursor.into();
    }
    call(operation, &variables)
}

#[must_use]
pub fn user_by_handle(handle: &str) -> Request { call("UserByScreenName", &json!({"screen_name": handle})) }

/// The timelines the account pinned beside For You and Following on x.com's home page.
#[must_use]
pub fn pinned_timelines() -> Request { call("PinnedTimelines", &json!({})) }

/// The two home timelines are POSTs, as x.com's app sends them; every other call is a GET.
fn call(operation: &str, variables: &Value) -> Request {
    let specs = &*GRAPHQL;
    let id = specs[operation]["queryId"].as_str().expect("graphql.json names each call's queryId");
    let own_or_shared = |key: &str| if specs[operation][key].is_null() { &specs[key] } else { &specs[operation][key] };
    let (features, toggles) = (own_or_shared("features"), own_or_shared("fieldToggles"));
    let path = format!("/i/api/graphql/{id}/{operation}");
    if operation.starts_with("Home") {
        let body = json!({"variables": variables, "features": features, "fieldToggles": toggles, "queryId": id});
        return Request { path, body: Some(body.to_string()) };
    }
    let query = [("variables", variables), ("features", features), ("fieldToggles", toggles)]
        .map(|(k, v)| format!("{k}={}", encode(&v.to_string())));
    Request { path: format!("{path}?{}", query.join("&")), body: None }
}

/// Percent-encoding for a URL's path or query: every byte but the unreserved characters of RFC 3986.
#[must_use]
pub fn encode(text: &str) -> String {
    text.bytes().fold(String::with_capacity(text.len() * 3), |mut out, b| {
        if b.is_ascii_alphanumeric() || b"-._~".contains(&b) {
            out.push(char::from(b));
        } else {
            _ = write!(out, "%{b:02X}");
        }
        out
    })
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("not JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("X answered with an error: {0}")]
    Api(String),
    #[error("no timeline in the answer")]
    NoTimeline,
    #[error("no such account, or it is suspended")]
    NoUser,
}

#[derive(Debug, Clone, PartialEq)]
pub struct User {
    pub name: String,
    pub handle: String,
    pub avatar: String,
    pub badge: Option<Badge>,
    pub affiliate: Option<Affiliate>,
}

/// The check X draws after a name: blue for X Premium, gold for an organisation, grey for a government or one of its
/// officials.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Badge {
    Blue,
    Gold,
    Grey,
}

/// The organisation an account belongs to, which X shows after its name as the organisation's picture.
#[derive(Debug, Clone, PartialEq)]
pub struct Affiliate {
    pub name: String,
    pub handle: String,
    pub avatar: String,
}

/// A video's or GIF's MP4: the best one at or under `VIDEO_BITRATE`, else the smallest. One X sends with no MP4
/// is a `Photo` of its still.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MediaKind {
    Photo,
    Video(String),
    Gif(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Media {
    pub kind: MediaKind,
    /// The image, or a video's still frame.
    pub url: String,
    /// Its width and height in pixels, when X sent both.
    pub size: Option<(u32, u32)>,
}

/// X's 480p rung, 832 kbit/s, is the best MP4 under this, and a weak laptop decodes it smoothly.
const VIDEO_BITRATE: u64 = 1_000_000;

/// A run of a post's text: plain, or one of the entities X marks in it.
#[derive(Debug, Clone, PartialEq)]
pub enum Segment {
    Text(String),
    /// A link as X shows it (`display_url`, shortened) and where it goes (`expanded_url`), always http or https.
    Link {
        shown: String,
        href: String,
    },
    Mention(String),
    Hashtag(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Post {
    pub id: String,
    pub author: User,
    pub text: Vec<Segment>,
    /// X's translation of `text` into the reader's language, sent with the post when X has one ready.
    pub translation: Option<Translation>,
    pub created_at: String,
    pub media: Vec<Media>,
    /// Who reposted it into the timeline, and when; the post itself is the original.
    pub repost: Option<Repost>,
    /// Pinned to the top of its author's profile, shown there first.
    pub pinned: bool,
    pub quote: Option<Box<Post>>,
    /// The post this one answers.
    pub reply_to: Option<String>,
    pub replies: u64,
    pub reposts: u64,
    pub likes: u64,
    pub views: Option<u64>,
}

/// A repost's own author and time, apart from the original's.
#[derive(Debug, Clone, PartialEq)]
pub struct Repost {
    pub by: User,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Translation {
    /// The language translated from, a tag such as "de" that `Intl.DisplayNames` takes.
    pub from: String,
    pub text: Vec<Segment>,
}

#[derive(Debug, Default, PartialEq)]
pub struct Page {
    pub posts: Vec<Post>,
    /// The cursor for the next, older page.
    pub next: Option<String>,
}

/// A timeline answer (home, list, community, profile tab or post page) into its posts and the cursor past them.
/// Ads are left out.
pub fn parse_timeline(text: &str) -> Result<Page, Error> {
    let data = answer(text)?;
    let instructions = find_key(&data, "instructions").and_then(Value::as_array).ok_or(Error::NoTimeline)?;
    // A post page's "Discover more": posts from across X, answering nothing there, added once its replies run out.
    let related = |e: &Value| e["entryId"].as_str().is_some_and(|id| id.starts_with("tweetdetailrelatedtweets-"));
    let past_replies = instructions.iter().any(|i| items(&i["entries"]).iter().any(related));
    let mut page = Page::default();
    for instruction in instructions {
        page.posts.extend(module(&instruction["moduleItems"])); // a Media tab's later pages, added to the module its first page opened
        let pinned = instruction["type"] == "TimelinePinEntry"; // a profile's pinned post, before its other entries
        // TimelineAddEntries' entries, or the one entry of a TimelineReplaceEntry or TimelinePinEntry.
        for content in items(&instruction["entries"]).iter().chain([&instruction["entry"]]).filter(|&e| !related(e)).map(|e| &e["content"]) {
            page.posts.extend(item_post(&content["itemContent"]).map(|p| Post { pinned, ..p }));
            page.posts.extend(module(&content["items"])); // a conversation: the thread's posts in order
            if content["cursorType"] == "Bottom" {
                page.next = content["value"].as_str().map(str::to_owned);
            }
        }
    }
    // X sends a bottom cursor past the end too: on a timeline's empty pages, and after a post page's "Discover more".
    Ok(Page { next: page.next.filter(|_| !past_replies && !page.posts.is_empty()), ..page })
}

/// An answer's `data`, or X's error when it sent one instead.
fn answer(text: &str) -> Result<Value, Error> {
    let mut root: Value = serde_json::from_str(text)?;
    match root["errors"][0]["message"].as_str() {
        Some(message) if root["data"].is_null() => Err(Error::Api(message.to_owned())),
        _ => Ok(root.get_mut("data").map_or(Value::Null, Value::take)), // not `root["data"]`: it panics on a non-object
    }
}

/// A profile's header: who it is, what they wrote about themselves, and their counts.
#[derive(Debug, Clone, PartialEq)]
pub struct Profile {
    /// The `rest_id` their timeline is asked for by.
    pub id: String,
    pub user: User,
    pub bio: Vec<Segment>,
    pub location: String,
    /// As X shows it (`display_url`) and where it goes, always http or https.
    pub website: Option<(String, String)>,
    /// "Sat Dec 14 04:35:55 +0000 2013"
    pub joined: String,
    pub banner: Option<String>,
    pub following: u64,
    pub followers: u64,
    pub posts: u64,
}

/// A `UserByScreenName` answer. X moved most profile fields out of `legacy` in 2025; older answers keep them there.
pub fn parse_profile(text: &str) -> Result<Profile, Error> {
    let data = answer(text)?;
    let result = &data["user"]["result"];
    if result["__typename"] != "User" {
        return Err(Error::NoUser); // absent for no such handle, "UserUnavailable" when suspended
    }
    let legacy = &result["legacy"];
    let new_or_old = |new: &Value, old: &Value| if new.is_null() { old.clone() } else { new.clone() };
    let bio = new_or_old(&result["profile_bio"], &json!({"description": legacy["description"], "entities": legacy["entities"]}));
    let count = |new: &Value, old: &Value| new.as_u64().or(old.as_u64()).unwrap_or(0);
    let website = new_or_old(&bio["entities"]["url"]["urls"][0], &legacy["entities"]["url"]["urls"][0]);
    Ok(Profile {
        id: id(&result["rest_id"]).ok_or(Error::NoUser)?,
        user: user(result).ok_or(Error::NoUser)?,
        bio: split(bio["description"].as_str().unwrap_or_default(), &bio["entities"]["description"], None, true),
        location: new_or_old(&result["location"]["location"], &legacy["location"]).as_str().unwrap_or_default().to_owned(),
        website: web(&website["expanded_url"]).map(|href| (website["display_url"].as_str().unwrap_or(href).to_owned(), href.to_owned())),
        joined: new_or_old(&result["core"]["created_at"], &legacy["created_at"]).as_str().unwrap_or_default().to_owned(),
        banner: banner(&new_or_old(&result["banner"]["image_url"], &legacy["profile_banner_url"])),
        following: count(&result["relationship_counts"]["following"], &legacy["friends_count"]),
        followers: count(&result["relationship_counts"]["followers"], &legacy["followers_count"]),
        posts: count(&result["tweet_counts"]["tweets"], &legacy["statuses_count"]),
    })
}

/// A `PinnedTimelines` answer: the lists and communities the account pinned as tabs on x.com's home page, by name,
/// in its order. Pinned topics are left out.
pub fn parse_pinned(text: &str) -> Result<Vec<(String, Timeline)>, Error> {
    let data = answer(text)?;
    let tab = |item: &Value| {
        let (found, timeline): (&Value, fn(String) -> Timeline) = match item["__typename"].as_str()? {
            "ListPinnedTimeline" => (&item["list"], Timeline::List),
            "CommunityPinnedTimeline" => (&item["community_results"]["result"], Timeline::Community),
            _ => return None,
        };
        Some((found["name"].as_str()?.to_owned(), timeline(id(&found["id_str"])?)))
    };
    Ok(items(&data["pinned_timelines"]["pinned_timelines"]).iter().filter_map(tab).collect())
}

/// A post's, account's, list's or community's id: digits only, as X's are, so it can stand in a path.
fn id(v: &Value) -> Option<String> { v.as_str().filter(|s| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit())).map(str::to_owned) }

/// A handle as X allows one, 1 to 15 letters, digits and underscores, so it can stand in a path: `/<handle>`
/// leaves x.com when the handle starts with `/`.
#[must_use]
pub fn is_handle(text: &str) -> bool { (1..=15).contains(&text.len()) && text.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') }

/// An address a link may open: http or https, never `javascript:` or `data:`, which run in the page they open from.
fn web(url: &Value) -> Option<&str> { url.as_str().filter(|u| u.starts_with("https://") || u.starts_with("http://")) }

/// A profile banner on X's image host, in characters that cannot end the client's unquoted CSS `url(...)`.
fn banner(url: &Value) -> Option<String> {
    let url = url.as_str()?;
    let path = url.strip_prefix("https://pbs.twimg.com/")?;
    path.bytes().all(|b| b.is_ascii_alphanumeric() || b"/_-.".contains(&b)).then(|| url.to_owned())
}

/// An array's items; none when `value` is absent or not an array.
fn items(value: &Value) -> &[Value] { value.as_array().map_or(&[], Vec::as_slice) }

/// A module's posts: a conversation's thread, or a Media tab's grid.
fn module(value: &Value) -> impl Iterator<Item = Post> { items(value).iter().filter_map(|i| item_post(&i["item"]["itemContent"])) }

/// The first value under `key` anywhere in `value`, depth first: each timeline nests its instructions elsewhere.
fn find_key<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key).or_else(|| map.values().find_map(|v| find_key(v, key))),
        Value::Array(items) => items.iter().find_map(|v| find_key(v, key)),
        _ => None,
    }
}

fn item_post(item: &Value) -> Option<Post> {
    if item["itemType"] != "TimelineTweet" || !item["promotedMetadata"].is_null() {
        return None;
    }
    post(&item["tweet_results"]["result"])
}

fn post(result: &Value) -> Option<Post> {
    let tweet = match result["__typename"].as_str()? {
        "Tweet" => result,
        "TweetWithVisibilityResults" => &result["tweet"],
        _ => return None, // a tombstone: deleted, withheld or from a protected account
    };
    let legacy = &tweet["legacy"];
    let author = user(&tweet["core"]["user_results"]["result"])?;
    let created_at = legacy["created_at"].as_str().unwrap_or_default().to_owned();
    let original = &legacy["retweeted_status_result"]["result"];
    if !original.is_null() {
        return Some(Post { repost: Some(Repost { by: author, created_at }), ..post(original)? });
    }
    let count = |key: &str| legacy[key].as_u64().unwrap_or(0);
    Some(Post {
        id: id(&tweet["rest_id"])?,
        author,
        text: text(tweet),
        translation: translation(&tweet["grok_translated_post_with_availability"]),
        created_at,
        media: media(legacy),
        repost: None,
        pinned: false,
        quote: post(&tweet["quoted_status_result"]["result"]).map(Box::new),
        reply_to: id(&legacy["in_reply_to_status_id_str"]),
        replies: count("reply_count"),
        reposts: count("retweet_count").saturating_add(count("quote_count")),
        likes: count("favorite_count"),
        views: tweet["views"]["count"].as_str().and_then(|v| v.parse().ok()),
    })
}

/// X moved name and handle from `legacy` to `core`, the picture to `avatar` and the badge's kind to `verification`, in
/// 2025; older answers keep `legacy`.
fn user(result: &Value) -> Option<User> {
    let pick = |new: &Value, old: &Value| new.as_str().or(old.as_str()).map(str::to_owned);
    let badge = match pick(&result["verification"]["verified_type"], &result["legacy"]["verified_type"]).as_deref() {
        Some("Business") => Some(Badge::Gold),
        Some("Government") => Some(Badge::Grey),
        _ => (result["is_blue_verified"] == true).then_some(Badge::Blue),
    };
    Some(User {
        name: pick(&result["core"]["name"], &result["legacy"]["name"])?,
        handle: pick(&result["core"]["screen_name"], &result["legacy"]["screen_name"]).filter(|h| is_handle(h))?,
        avatar: pick(&result["avatar"]["image_url"], &result["legacy"]["profile_image_url_https"]).unwrap_or_default(),
        badge,
        affiliate: affiliate(&result["affiliates_highlighted_label"]["label"]),
    })
}

/// An account's affiliation: the organisation's name, its picture, and its profile, which X links as
/// `https://twitter.com/<handle>`. Left off when any part fails its check.
fn affiliate(label: &Value) -> Option<Affiliate> {
    let link = label["url"]["url"].as_str()?;
    let handle = ["https://twitter.com/", "https://x.com/"].iter().find_map(|site| link.strip_prefix(site)).filter(|h| is_handle(h))?;
    Some(Affiliate {
        name: label["description"].as_str()?.to_owned(),
        handle: handle.to_owned(),
        avatar: web(&label["badge"]["url"])?.to_owned(),
    })
}

/// X's ready translation of a post (`grok_translated_post_with_availability`), when it has one. X sends the translation's
/// own entities, counted in the translated text.
fn translation(found: &Value) -> Option<Translation> {
    if found["is_available"] != true {
        return None;
    }
    let data = &found["data"];
    let from = data["source_language"].as_str().filter(|tag| is_language(tag))?.to_owned();
    Some(Translation { from, text: split(data["translation"].as_str()?, &data["entities"], None, false) })
}

/// A language tag in a shape `Intl.DisplayNames` takes, as it throws on others: a language, then a region or a script
/// ("de", "pt-BR", "zh-Hant").
fn is_language(tag: &str) -> bool {
    let (language, rest) = tag.split_once('-').map_or((tag, None), |(l, r)| (l, Some(r)));
    let letters = |s: &str, lengths: &[usize]| lengths.contains(&s.len()) && s.bytes().all(|b| b.is_ascii_alphabetic());
    letters(language, &[2, 3]) && rest.is_none_or(|r| letters(r, &[2, 4]))
}

/// The post's own words: a long post's full text, else `full_text` within its display range, which leaves out
/// the trailing media link. Only `full_text` comes HTML-encoded, its entities counted in the encoded text, so its runs
/// are decoded after the split; a long post's text and a bio come as written.
fn text(tweet: &Value) -> Vec<Segment> {
    let (note, legacy) = (&tweet["note_tweet"]["note_tweet_results"]["result"], &tweet["legacy"]);
    let Some(text) = note["text"].as_str() else {
        let full = split(legacy["full_text"].as_str().unwrap_or_default(), &legacy["entities"], Some(&legacy["display_text_range"]), false);
        return full.into_iter().map(|s| if let Segment::Text(t) = s { Segment::Text(decode(&t)) } else { s }).collect();
    };
    split(text, &note["entity_set"], None, false)
}

/// `raw` split at the `entities` X marks in it, within `range` when given: a post's text or a profile's bio.
/// Entity indices count characters of the text as X sends it. With `handles`, the @handles X leaves unmarked are marked
/// too: a bio's.
fn split(raw: &str, entities: &Value, range: Option<&Value>, handles: bool) -> Vec<Segment> {
    let chars: Vec<char> = raw.chars().collect();
    let end = range.and_then(|r| r[1].as_u64()).map_or(chars.len(), |e| usize::try_from(e).unwrap_or(usize::MAX).min(chars.len()));
    let start = range.and_then(|r| r[0].as_u64()).map_or(0, |s| usize::try_from(s).unwrap_or(0).min(end));
    let index = |e: &Value, i: usize| e["indices"][i].as_u64().and_then(|v| usize::try_from(v).ok());
    // Each entity's span, and what replaces it there: `None` cuts it out.
    let mark = |e: &Value, segment: Option<Segment>| Some((index(e, 0)?, index(e, 1)?, segment));
    let list = |key: &str| items(&entities[key]).iter();
    // The media link is cut out, as media shared from another post leaves it inside the display range.
    let mut marks: Vec<_> = list("media").filter_map(|m| mark(m, None)).collect();
    // A mention or link that fails its check (`is_handle`, `web`) is not marked: the text it covers shows as text.
    let mention = |e: &Value| Some(Segment::Mention(e["screen_name"].as_str().filter(|h| is_handle(h))?.to_owned()));
    marks.extend(list("user_mentions").filter_map(|e| mark(e, Some(mention(e)?))));
    marks.extend(list("hashtags").filter_map(|e| mark(e, Some(Segment::Hashtag(e["text"].as_str()?.to_owned())))));
    marks.extend(list("urls").filter_map(|u| {
        let href = web(&u["expanded_url"])?;
        mark(u, Some(Segment::Link { shown: u["display_url"].as_str().unwrap_or(href).to_owned(), href: href.to_owned() }))
    }));
    // X marks only a bio's links, and its own app finds the handles in the text, as twitter-text does: an @ after none
    // of a letter, digit, `_` or `!#$%&*@`, then a handle that runs on into no other letter, an @ or `://`.
    let word = |c: char| c.is_ascii_alphanumeric() || c == '_';
    let starts = |i: usize| handles && chars[i] == '@' && (i == 0 || !(word(chars[i - 1]) || "!#$%&*@".contains(chars[i - 1])));
    marks.extend((0..chars.len()).filter(|&i| starts(i)).filter_map(|i| {
        let end = (i + 1..chars.len()).find(|&j| !word(chars[j])).unwrap_or(chars.len());
        let (handle, rest): (String, String) = (chars[i + 1..end].iter().collect(), chars[end..].iter().take(3).collect());
        let ends = !rest.starts_with(|c: char| c == '@' || c.is_alphabetic()) && !rest.starts_with("://");
        (is_handle(&handle) && ends).then_some((i, end, Some(Segment::Mention(handle))))
    }));
    marks.sort_by_key(|m| m.0);
    let mut out = Vec::new();
    let mut at = start;
    for (a, b, segment) in marks {
        if a < at || b > end || a >= b {
            continue; // overlapping, or outside the shown range: the trailing media link
        }
        if a > at {
            out.push(Segment::Text(chars[at..a].iter().collect()));
        }
        out.extend(segment);
        at = b;
    }
    if at < end {
        out.push(Segment::Text(chars[at..end].iter().collect()));
    }
    if let Some(Segment::Text(last)) = out.last_mut() {
        last.truncate(last.trim_end().len()); // the space before a cut media link
    }
    out
}

/// The three HTML entities X encodes in `full_text`.
fn decode(text: &str) -> String { text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&") }

fn media(legacy: &Value) -> Vec<Media> {
    items(&legacy["extended_entities"]["media"])
        .iter()
        .filter_map(|m| {
            let size = |key: &str| m["original_info"][key].as_u64().and_then(|v| u32::try_from(v).ok()).filter(|&v| v > 0);
            let mp4s: Vec<(u64, &str)> = items(&m["video_info"]["variants"])
                .iter()
                .filter(|v| v["content_type"] == "video/mp4")
                .filter_map(|v| Some((v["bitrate"].as_u64().unwrap_or(0), v["url"].as_str()?)))
                .collect();
            let fits = mp4s.iter().filter(|(b, _)| *b <= VIDEO_BITRATE).max_by_key(|(b, _)| *b);
            let video = fits.or_else(|| mp4s.iter().min_by_key(|(b, _)| *b)).map(|(_, url)| (*url).to_owned());
            let kind = match (m["type"].as_str()?, video) {
                ("video", Some(mp4)) => MediaKind::Video(mp4),
                ("animated_gif", Some(mp4)) => MediaKind::Gif(mp4),
                ("photo" | "video" | "animated_gif", _) => MediaKind::Photo,
                _ => return None,
            };
            Some(Media { kind, url: m["media_url_https"].as_str()?.to_owned(), size: size("width").zip(size("height")) })
        })
        .collect()
}
