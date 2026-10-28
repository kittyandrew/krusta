# krusta design

## Why an extension inside x.com

X's own web app ships about 940 KB of gzipped JavaScript before the logged-out shell is usable (measured Oct
27, 2026), and is slow on a low-powered laptop. kitter replaces that app, not the site: it runs in the x.com tab
on the browser's existing session.

- **No login of its own.** X blocks scripted sign-in (twscrape's maintainer, Oct 21, 2026: "X blocks scripted
  login now"), and a page outside x.com cannot use the session: X sends no `Access-Control-Allow-Credentials`.
  Running inside x.com makes kitter's requests the page's own, same-origin, with its cookies.
- **No server and no TLS impersonation.** The browser's real TLS and network stack talk to X, so Cloudflare's
  checks on non-browser clients do not apply.
- **The official API was ruled out.** It has no For You and no notifications endpoint, and costs about $150 a
  month for 1,000 posts a day (docs.x.com pricing, Oct 2026).

Using the web API breaks X's terms of service; the account is Andrew's own, read at a human pace.

## Sites

krusta is one add-on for any number of sites, each through an interface of its own: so far kitter, for X. The
shell in `extension/` is the same for all of them: it takes the page over, keeps the site's own app out, lends
the interface the page's session and owns the toolbar button. Everything about one interface lives in
`sites/<id>/`, the folder named after it, and the build finds each folder there.
The name also titles the button and names its crates; a tab keeps the site's own title and icon. Each
interface's client is its own wasm, loaded only on its site: a new one never makes kitter heavier. There is no
shared Rust crate yet; one comes when a second interface shows what it shares (Oct 28, 2026).

Adding an interface `<id>`:

1. `sites/<id>/site.json`: `site`, the site it replaces as people know it (kitter's is "X (Twitter)"); `hosts`
   (the shell runs on `https://<host>/*`); `signIn`, a regex of the paths left to the site; `api`, the path prefix
   of the site's API, the only paths `krustaFetch` sends; `appScripts`, URL prefixes of the site's own app scripts,
   cancelled when loaded with no tab.
2. `sites/<id>/api/`, crate `<id>-api`: the site's web API and parsers, native, no browser.
3. `sites/<id>/web/`, crate `<id>-web`, a `cdylib` exporting `start()` that draws by path, calling the site
   through `krustaFetch(path, body, headers)`. Add its API crate to the workspace dependencies.
4. `sites/<id>/style.css`.
5. `sites/<id>/tests/vm.nix`, which becomes flake check `vm-<id>`: a fake of the site from recorded answers, the
   shell's scenarios against it (takeover, `?krusta=off`, the button), and the site's own, each with a plant.
6. A line in `README.md`. The manifest's hosts and resources, `sites.js` and the cookies `tests/zen.sh` copies
   come from `site.json` by themselves.

## How a tab becomes kitter

What follows is the shell as X uses it; another site goes through the same steps with its own `site.json`.

1. `content.js` runs at `document_start`, before any of x.com's HTML is parsed or any of its scripts run, and
   calls `window.stop()`, which aborts the page's parser: none of x.com's app arrives. It empties the page,
   links the site's icon at `/favicon.ico`, loads the wasm client there, then calls `start()`. Replacing the
   HTML in `background.js` with `webRequest.filterResponseData` was the first design; Zen refused it with
   "Invalid request ID" on five of six loads in Andrew's profile, and the filter then let x.com's HTML through
   (Oct 27, 2026).
2. `background.js` drops the page's CSP so the client's stylesheet loads. A kitter tab's own scripts need no
   blocking: `window.stop()` ends the page before it asks for any. x.com's service worker answers pages and
   bundles from its own cache, past every handler: a profile that had visited x.com got X's app back from cache
   (Oct 27, 2026). So krusta removes x.com's service workers at install and at each browser start, and cancels
   every script loaded with no tab, which is how Firefox loads a worker's. It keeps nothing per tab: Firefox
   stops this event page after 30 s idle, and a sign-in that took longer had its next script cancelled by a
   forgotten list (Oct 28, 2026). After an install or update it reloads x.com's open tabs, whose content
   scripts Firefox kills, leaving the page drawn but dead.
3. The client calls X's API through `krustaFetch`, the content script's `fetch`, which Firefox sends in MV3
   with the page's origin: the request is x.com's own, so the browser adds the session cookies. `ct0` goes
   back as `x-csrf-token`. MV2's `content.fetch` does not exist in MV3 (a ReferenceError in Zen, Oct 27, 2026).
   `krustaFetch` takes a path, resolves it on the page's origin, dot segments included, and refuses one outside
   `/i/api/graphql/` (site.json's `api`): the client's headers carry the CSRF token, so a client bug cannot spend
   them on another of x.com's endpoints.
4. `start()` draws by path: `/` and `/home` are the home page, a top-level path that can be a handle is that
   profile (x.com's own pages there, such as `/settings`, are listed in `NOT_HANDLES`), `/<handle>/status/<id>`
   that post's page, anything else a page that points to the toolbar button, which opens it on x.com. Links
   between kitter's pages are plain page loads, each turned into kitter again. Every page's bar holds the home
   tabs, which elsewhere open `/home#<tab>`, and every page takes x.com's title for it ("Home / X").

X's sign-in pages and any page opened with `?krusta=off` stay x.com, so signing in, and anything kitter does
not draw yet, still works: a signed-out `/home` redirects to X's onboarding flow, which kitter does not draw. That
tab stays x.com until it loads x.com again without the flag.

krusta's toolbar button turns it off for the site of the tab it is clicked in, to compare with the site's own app
or to get past something kitter breaks, and on again; each click reloads that tab, and the badge says "off" in
the site's tabs while it is off. So `background.js` registers `content.js` per site at run time
(`scripting.registerContentScripts`) instead of in the manifest, and unregisters it when the site is off; the
choice is kept in `storage.local` across restarts. Off, it still blocks the site's service worker, which would
otherwise serve the site's app to krusta tabs once krusta is on again. Zen puts the button in its extensions menu
at first; pin it from there to keep it on the toolbar.

## Talking to X

- **Calls** go to `/i/api/graphql/<queryId>/<operation>` with the public web bearer token and the headers x.com's
  app sends. HomeTimeline (For You) and HomeLatestTimeline (Following) are POSTs of `{variables, features,
  fieldToggles, queryId}`, as x.com's app sends them; ListLatestTweetsTimeline, CommunityTweetsTimeline,
  UserTweets, UserTweetsAndReplies, UserMedia, UserByScreenName, PinnedTimelines and TweetDetail are GETs with
  the same three as JSON in the query.
- **Profiles** have X's Posts, Replies and Media tabs (UserTweets, UserTweetsAndReplies, UserMedia). Likes is left
  out: X shows an account's likes only to that account. A Media tab's first page is one module of posts, its
  later pages `TimelineAddToModule` instructions adding to it; the VM's recording has no later page.
- **A post's page** (TweetDetail, `focalTweetId`) lists the thread it answers, the post, then its replies, each
  reply thread as a module in X's order; the post itself is marked and scrolled to, and more replies page in
  through the bottom cursor like a timeline. Its "Discover more" module (`tweetdetailrelatedtweets-<n>`, posts
  from across X) is left out. Replies X hides behind "Show more replies" (`cursor-showmorethreads-<n>`) are not
  reached yet (Oct 28, 2026).
- **Threads** are joined by a line, as on X: from a post's avatar to the next post's, when that one answers it
  (`in_reply_to_status_id_str`), in every timeline. On a post's page, the post itself joins only its author's
  next post, so a thread it starts reads on from it, but a stranger's reply does not.
- **Query ids and features** come from x.com's current bundle through fa0311/TwitterInternalAPIDocument
  (`sites/kitter/api/src/graphql.json`, Oct 27, 2026). HomeTimeline's values follow twscrape's defaults where it
  has one, else `false`, so newer response formats stay off; the other calls share them, and take the document's
  defaults for switches of their own.
- **Pinned tabs**: PinnedTimelines lists what the account pinned beside For You and Following. kitter shows its
  lists (ListLatestTweetsTimeline) and communities (CommunityTweetsTimeline, in the community's Top order, as
  twscrape asks it) as tabs; pinned topics are left out. A community's id is its `id_str`; it has no `rest_id`.
- **`x-client-transaction-id`** is not sent, and X serves HomeTimeline without it: the For You feed loaded and
  paged in Andrew's Zen (Oct 27, 2026). If X starts demanding it, compute it from the `/i/jf/` page's key, as
  XClientTransaction does.
- **What X sends is checked where it is parsed**, since each value ends up in a path, a link or CSS: handles as X
  allows them (1 to 15 letters, digits and underscores), ids of digits only, links and a profile's website only at
  `http:` or `https:` addresses, banners only on `https://pbs.twimg.com/` in characters that cannot end CSS's
  `url(...)`. A post or account that fails is left out; a mention or link that fails stays the text it covers, and
  a website or banner is left off. Otherwise a handle such as `/evil.example` would link to `//evil.example`, and a
  `javascript:` link would run in x.com's page, whose CSP krusta drops. Hashtags are percent-encoded in their path.
- **Parsing** walks the JSON for `instructions` and keeps tweets, reposts (shown as the original with who
  reposted it), quotes, threads, a profile's pinned post (`TimelinePinEntry`, shown first) and the bottom
  cursor, and drops ads. A post a later page repeats is shown once. Users and profiles read X's 2025 fields
  (`core`, `avatar`, `profile_bio`, `relationship_counts`, `banner`), falling back to `legacy`.

## Posts and media

- **A click** anywhere in a post opens its page, and in a quote the quoted post's, except on a link, button,
  photo or video, or when it ends a text selection; the date links there too, and the avatar to the profile. One
  click listener serves the whole page. A quoted post's byline starts with a small avatar, as on X, having no
  avatar column.
- **Text** is split at X's entities: links open in a new tab at their full address and show X's short form;
  @mentions and authors' names open their kitter profile, #hashtags open on x.com (`?krusta=off`). Entity indices
  count the text as X sends it, with `&amp;` still encoded, so the split comes before decoding. The media link is
  always cut: media shared from another post leaves it inside `display_text_range`.
- **Media** follows X's layouts: one at its own shape (capped at 32rem), two side by side, three as one tall and
  two stacked, four in a square; past four, the first four.
- **Photos** load at X's `small` size (680 px wide at most) and open in a viewer at `large` (2048 px at most);
  the arrow keys step through the post's photos, Escape or a click closes it.
- **Videos** play inline from the best MP4 at or under 1 Mbit/s (X's 480p rung), so a weak laptop decodes them
  smoothly; `preload="none"` loads nothing before play. **GIFs** (MP4s on X) loop muted and play only while on
  screen, through one IntersectionObserver in `content.js`. One X sends with no MP4 shows as a photo of its still.

## Speed

- The client is 120 KB of gzipped wasm plus 7 KB of gzipped JS glue (Oct 28, 2026), against x.com's ~940 KB of
  gzipped JS. Its sizes as loaded are budgets below.
- Off-screen posts skip layout and paint (`content-visibility: auto`); images load lazily and decode off the
  main thread. The next page starts loading six screens before the end, enough to hide X's ~1 s answer at a
  quick flick.
- Not built yet: virtualization (the DOM grows as you scroll).

## Testing

No unit tests: each suite runs the real program and is its own flake check. `vm-kitter` installs the .xpi by
policy in Firefox Developer Edition (release Firefox takes only signed add-ons) inside a NixOS VM. A fake X there
serves x.com, abs.twimg.com, pbs.twimg.com and video.twimg.com over TLS from a test CA. Its answers are twscrape's
recordings, fetched by hash (a list timeline, @XDevelopers' profile and posts, a post's page, another account's
replies and media, a community), plus derived ones (three photos, a shared GIF, two hostile posts, a second
page, Following, a pinned list and community, and "Discover more" on the post's page). It checks each call's query
id, method and feature switch names as X does. Its access log proves what a kitter tab never fetched. WebDriver
never sees a kitter page finish loading (content.js stops x.com's), so the scenarios navigate with the "none"
page-load strategy and wait for the new document themselves (`go`). The toolbar button is clicked in the
browser's own window, WebDriver's chrome context, which geckodriver opens with `--allow-system-access`. From there
the `api-only` scenario also calls `krustaFetch`, which the page cannot reach, in the content script's own world
through Firefox's ExtensionContent actor, as the add-on's `scripting.executeScript` would. Each
scenario has a planted bug that fails it (`.plants`); a failed run keeps its evidence in the store. Not covered:
a service worker x.com registered before krusta was installed (a force-installed add-on cannot be removed to
prepare that profile), and whether dropping x.com's CSP is needed against X's real policy (a strict test CSP did
not block the content script's stylesheet). The fake checks a call's feature switches but not its variables: X
answered TweetDetail 422 for a missing `withBirdwatchNotes`, which only the live check in the test Zen showed
(Oct 28, 2026). So check a new call live (`.claude/rules/004-zen.md`) before trusting the VM's green.

## Speed budgets

`sites/kitter/tests/budgets/run.sh` measures these on the development machine in a headless Firefox with kitter
installed, against a fake x.com serving twscrape's recorded timeline (about 94 posts a page, next pages answered
after 1 s, assumed from the bench below), and fails above them. Not in a VM, which kubicle measured two to five
times slower.
Each is a median of several runs; measured on palanok, Oct 27, 2026, after tabs, profiles and the six-screen
prefetch. With the old two-screen prefetch, the stall budget failed at 148 frames.

| Budget | Limit | Measured median |
|---|---|---|
| Navigation to the first posts | 200 ms | 82 to 205 ms, median 101 ms (Oct 28, 2026) |
| Worst frame while paging 5 pages | 100 ms | 50 ms |
| Frames dropped while paging 5 pages | 16 | 4 to 8, about one per page appended |
| Frames stalled at the feed's end | 1 | 0 |
| JS heap after 5 pages | 32 MB | 22.3 MB |
| DOM nodes after 5 pages | 8000 | 7232, about 15 elements a post: the avatar floats in the post's padding, no wrappers (Oct 28, 2026) |
| wasm loaded | 300 KB | 277.8 KB: tabs, communities, profiles and the post page took it past the old 240 KB (Oct 28, 2026) |
| JS and CSS loaded | 50 KB | 48.2 KB: the full Frappe theme, the post page and thread lines (Oct 28, 2026) |

## Against x.com

`sites/kitter/tests/bench/` is a second add-on that compares kitter with x.com's own app on Andrew's session,
the only signed-in x.com. Its `run.sh` installs it beside kitter in a headless Zen of its own (`tests/zen.sh`):
a fresh profile holding only a copy of his x.com cookies, so his browser is never touched. The add-on at once loads
x.com/home five times as each (`?krusta=off` for x.com's app), alternating, in one tab, then runs the memory rounds
below, and saves `kitter-bench-<time>.json` with the medians and every run. A content script measures each
load the same way: the first post on screen, two seconds of rest, then 300 frames scrolling 80 px each (4,800
px/s, as the budgets scroll).
Medians of three runs in Andrew's own Zen on palanok, before the separate instance existed, Oct 27, 2026; runs 2
and 3 after the prefetch moved from two screens to six:

| Measure | kitter 1 | x.com 1 | kitter 2 | x.com 2 | kitter 3 | x.com 3 |
|---|---|---|---|---|---|---|
| First post on screen | 2.4 s | 3.8 s | 1.5 s | 2.6 s | 2.3 s | 3.7 s |
| Worst frame while scrolling | 35 ms | 2,006 ms | 34 ms | 70 ms | 42 ms | 1,847 ms |
| Frames over 50 ms | 0 | 26 | 0 | 5 | 0 | 20 |
| Scrolled of 24,000 px | 18,173 | 24,000 | 24,000 | 17,757 | 24,000 | 23,364 |
| Elements in the page after | 942 | 3,398 | 1,013 | 2,926 | 1,003 | 3,312 |

x.com's app varies most between runs: its loads froze for about 2 s while scrolling in runs 1 and 3, and fell
behind the scroll instead in run 2. kitter's first post varies with X's answer (1.2 to 7.6 s). Run 1 showed the
two-screen prefetch letting a quick flick reach the end against X's real latency. Requests and bytes are left
out: x.com's own cache and cross-origin answers without Timing-Allow-Origin, counted as 0, make them say little.

Runs 4 to 6, each a median of five loads, in the headless instance of the bench's `run.sh` (Oct 27, 2026). Both
apps start faster there than in runs 1 to 3; why is not measured:

| Measure | kitter | x.com |
|---|---|---|
| First post on screen | 1.0 to 1.1 s | 1.7 to 1.9 s |
| Worst frame while scrolling | 33 ms | 66 to 100 ms |
| Frames over 50 ms | 0 | 4 to 7 |
| Scrolled of 24,000 px | 24,000 | 21,826 to 23,744 |
| Elements in the page after | 1,053 to 1,071 | 2,449 to 3,468 |

x.com's own app logs the copied session out after about 3.5 minutes of use, so each run's third memory round
fails: `.claude/rules/004-zen.md`, Traps.

**Where a first post's time goes**, from one kitter load's resource timing: x.com's HTML starts arriving at
320 ms (kitter needs only the page it gives), the client is running and asking at 378 ms, and HomeTimeline
answers at 1,775 ms: X ranking For You is most of it. Every request in Andrew's Zen also waits 170 to 300 ms
before it is sent, on any site (example.com too) and from the page itself, not only from kitter, while a fresh
Zen or Firefox on the same machine waits 0 to 60 ms, with the policy's tracking protection on or uBlock Origin
installed alike. The instance of `tests/zen.sh`, a fresh profile of the same Zen under the same system policies,
waits as long: 180 to 530 ms before a request on a new connection, 0 to 8 ms on a reused one. So the cause is
not that profile's state. The wait counts DNS, connect and TLS, which are not split yet (Oct 27, 2026).

**Memory.** Firefox gives a page no heap figures, so the bench's `memory.py` reads them from outside: started
before the bench, it waits for the add-on's memory rounds, in which one kitter tab and one x.com tab each load
and scroll as above and stay open while the script sends Zen signal 34. Zen then writes a memory report of
every process (tried on a throwaway instance first: Zen handles the signal), and the script sums each tab's
explicit memory: the page (`window-objects`: DOM, layout, the page's own JS) and its content scripts, which
Firefox reports apart (`js-non-window`, a realm whose principal names the page): kitter's client and its wasm,
and every add-on's scripts in both tabs. x.com's workers are not counted. Medians of three rounds in Andrew's Zen,
and of six in the instance (two in each of runs 4 to 6), Oct 27, 2026:

| MB per tab | kitter, his Zen | x.com, his Zen | kitter, instance | x.com, instance |
|---|---|---|---|---|
| Page | 15.9 | 216.2 | 12.2 | 251.5 |
| Content scripts | 8.2 | 2.5 | 8.0 | 2.4 |
| Total | 23.9 | 218.8 | 20.2 | 253.9 |

A kitter tab used for an afternoon of testing, paged far further, held 128 MB in its client alone: whether the
client's memory grows with every page is not measured yet.
