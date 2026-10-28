//! kitter, krusta's interface for X. krusta's content script empties x.com's page and calls `start`; requests go to
//! x.com's own API from the page, so the browser's session cookies come along as they do for x.com's app.

use kitter_api::{Media, MediaKind, Post, Profile, Request, Segment, Timeline, encode};
use leptos::prelude::*;
use wasm_bindgen::{JsCast, prelude::*};
use wasm_bindgen_futures::JsFuture;
use web_sys::Response;

#[wasm_bindgen]
pub fn start() {
    window_event_listener(leptos::ev::click, open); // one listener for every post on the page, not one each
    title("X"); // until the page knows its own
    let path = window().location().pathname().unwrap_or_default();
    match *path.trim_matches('/').split('/').collect::<Vec<_>>() {
        ["" | "home"] => mount_to_body(home),
        [handle] if is_handle(handle) => {
            let handle = handle.to_owned();
            mount_to_body(move || shell(None, profile(handle)));
        }
        [handle, "status", id] if is_handle(handle) && id.bytes().all(|b| b.is_ascii_digit()) => {
            let id = id.to_owned();
            mount_to_body(move || shell(None, view! { <Posts which=Timeline::Post(id) /> }));
        }
        _ => mount_to_body(|| {
            let text = "kitter shows the home timelines, profiles and posts so far: krusta's toolbar button opens this page on x.com.";
            shell(None, view! { <p>{text}</p> })
        }),
    }
}

/// Every page: the bar, where kitter's name leads home, then the home page's tabs, For You, Following and the lists
/// and communities the account pinned there on x.com, then the page itself. `tab` is the home page's shown timeline.
fn shell(tab: Option<RwSignal<Timeline>>, body: impl IntoView) -> impl IntoView {
    let tabs = RwSignal::new(vec![("For you".into(), Timeline::ForYou), ("Following".into(), Timeline::Following)]);
    let error = RwSignal::new(None::<String>);
    leptos::task::spawn_local(async move {
        match fetch(kitter_api::pinned_timelines(), kitter_api::parse_pinned).await {
            Ok(found) => tabs.update(|t| t.extend(found)),
            Err(e) => error.set(Some(format!("pinned tabs: {e}"))),
        }
    });
    view! {
        <main class="kitter">
            <header class="bar"><a class="brand" href="/home">"kitter"</a>{tab_bar(tabs, tab)}</header>
            {move || error.get().map(|e| view! { <p class="error">{e}</p> })}
            {body}
        </main>
    }
}

/// x.com's own pages at a top-level path, which no account's handle can take.
const NOT_HANDLES: [&str; 16] = [
    "bookmarks", "communities", "compose", "explore", "home", "i", "jobs", "lists", "login", "logout", "messages", "notifications",
    "premium", "privacy", "search", "settings",
];

/// A handle as X allows one, and not one of x.com's own pages.
fn is_handle(path: &str) -> bool { kitter_api::is_handle(path) && !NOT_HANDLES.contains(&path.to_ascii_lowercase().as_str()) }

/// The home page: one of its tabs' timelines at a time, from the one the address names (`tab_key`), else For You.
fn home() -> impl IntoView {
    title("Home / X");
    let tab = RwSignal::new(tab_from_key(window().location().hash().unwrap_or_default().trim_start_matches('#')));
    shell(Some(tab), move || view! { <Posts which=tab.get() /> })
}

/// A profile at x.com/<handle>: its header, then its Posts, Replies and Media, the pinned post first.
fn profile(handle: String) -> impl IntoView {
    let profile = RwSignal::new(None::<Result<Profile, String>>);
    leptos::task::spawn_local(async move {
        let found = fetch(kitter_api::user_by_handle(&handle), kitter_api::parse_profile).await;
        if let Ok(p) = &found {
            title(&format!("{} (@{}) / X", p.user.name, p.user.handle));
        }
        profile.set(Some(found));
    });
    move || match profile.get() {
        None => view! { <p class="muted">"Loading…"</p> }.into_any(),
        Some(Err(e)) => view! { <p class="error">{e}</p> }.into_any(),
        Some(Ok(p)) => {
            let id = p.id.clone();
            let tabs = [
                ("Posts".into(), Timeline::User(id.clone())),
                ("Replies".into(), Timeline::Replies(id.clone())),
                ("Media".into(), Timeline::Media(id)),
            ];
            let tab = RwSignal::new(tabs[0].1.clone());
            view! { <ProfileHeader profile=p /> {tab_bar(RwSignal::new(tabs.into()), Some(tab))} {move || view! { <Posts which=tab.get() /> }} }
                .into_any()
        }
    }
}

/// A bar of tabs over `tabs`' timelines. With `tab`, a click shows its timeline in `tab` and marks it; without, as on a
/// profile or a post's page, the home tabs open the home page at theirs.
fn tab_bar(tabs: RwSignal<Vec<(String, Timeline)>>, tab: Option<RwSignal<Timeline>>) -> impl IntoView {
    let button = move |(label, which): (String, Timeline)| {
        let this = which.clone();
        let click = move |_| match tab {
            Some(tab) => tab.set(which.clone()),
            None => _ = window().location().set_href(&format!("/home#{}", tab_key(&which))),
        };
        view! { <button class="tab" class:on=move || tab.is_some_and(|t| t.with(|t| *t == this)) on:click=click>{label}</button> }
    };
    view! { <nav class="tabs">{move || tabs.get().into_iter().map(button).collect_view()}</nav> }
}

/// A home tab in the home page's address, `/home#<key>`: "following", "list-<id>" or "community-<id>", none for For You.
fn tab_key(timeline: &Timeline) -> String {
    match timeline {
        Timeline::Following => "following".into(),
        Timeline::List(id) => format!("list-{id}"),
        Timeline::Community(id) => format!("community-{id}"),
        _ => String::new(),
    }
}

fn tab_from_key(key: &str) -> Timeline {
    match key.split_once('-') {
        Some(("list", id)) => Timeline::List(id.into()),
        Some(("community", id)) => Timeline::Community(id.into()),
        _ if key == "following" => Timeline::Following,
        _ => Timeline::ForYou,
    }
}

#[component]
fn ProfileHeader(profile: Profile) -> impl IntoView {
    let Profile { user, bio, location, website, joined, banner, following, followers, posts, .. } = profile;
    // X's picture sizes: `_normal` is 48 px, `_200x200` sharp at the header's 96 px on a 2x screen.
    let avatar = user.avatar.replace("_normal.", "_200x200.");
    let words: Vec<&str> = joined.split(' ').collect(); // "Sat Dec 14 04:35:55 +0000 2013"
    let joined = format!("Joined {} {}", words.get(1).unwrap_or(&""), words.last().unwrap_or(&""));
    view! {
        <section class="profile">
            // A background, so a banner X names but cannot serve leaves the grey box x.com shows, not a broken
            // image. 1500x500 is the size x.com shows; not every banner has the others.
            <div class="banner" style:background-image=banner.map(|b| format!("url({b}/1500x500)"))></div>
            <img class="avatar big" src=avatar alt="" />
            <h1>{user.name}</h1>
            <p class="muted">{format!("@{}", user.handle)}</p>
            <Text segments=bio />
            <p class="muted meta">
                {(!location.is_empty()).then(|| view! { <span>{location}</span> })}
                {website.map(|(shown, href)| view! { <a href=href target="_blank" rel="noopener noreferrer">{shown}</a> })}
                <span>{joined}</span>
            </p>
            <p class="follows">
                <span><b>{compact(following)}</b>" Following"</span>
                <span><b>{compact(followers)}</b>" Followers"</span>
                <span class="muted">{format!("{} posts", compact(posts))}</span>
            </p>
        </section>
    }
}

/// A timeline's posts from its top, oldest pages appended as the reader nears the end.
#[component]
fn Posts(which: Timeline) -> impl IntoView {
    window().scroll_to_with_x_and_y(0.0, 0.0); // a tab switch starts the new timeline at its top
    let posts = RwSignal::new(Vec::<Post>::new());
    let next = RwSignal::new(None::<String>);
    let loading = RwSignal::new(false);
    let error = RwSignal::new(None::<String>);
    let viewer = Viewer(RwSignal::new(None));
    provide_context(viewer);
    let which = StoredValue::new(which); // so `load` stays Copy, shared by the scroll listener and the button
    let load = move || {
        if loading.get_untracked() {
            return;
        }
        loading.set(true);
        let cursor = next.get_untracked();
        let first = cursor.is_none();
        // A copy for the task: a tab switch while X answers drops `which`, and reading a dropped value panics (setting one
        // does nothing).
        let which = which.get_value();
        let request = kitter_api::timeline(&which, cursor.as_deref());
        leptos::task::spawn_local(async move {
            match fetch(request, kitter_api::parse_timeline).await {
                // A post seen on an earlier page is left out: For You repeats some, and each needs its own key.
                Ok(page) => {
                    if let Some(p) = page.posts.iter().find(|p| matches!(&which, Timeline::Post(id) if *id == p.id)) {
                        title(&format!("{} on X: \"{}\" / X", p.author.name, plain(&p.text)));
                    }
                    // X sends a bottom cursor on the empty pages past a timeline's end too: an empty page ends it.
                    next.set(page.next.filter(|_| !page.posts.is_empty()));
                    posts.update(|p| p.extend(page.posts.into_iter().filter(|n| !p.iter().any(|o| o.id == n.id)).collect::<Vec<_>>()));
                    error.set(None);
                    // A post's page opens on the post, the thread it answers above it, once that is drawn.
                    if first {
                        request_animation_frame(|| _ = document().query_selector(".post.focal").map(|e| e.map(|e| e.scroll_into_view())));
                    }
                }
                Err(e) => error.set(Some(e)),
            }
            loading.set(false);
        });
    };
    load();
    // The next page starts loading six screens before the end: at two, a quick flick met the bottom while X answered
    // (docs/design.md, Against x.com).
    let scroll = window_event_listener(leptos::ev::scroll, move |_| {
        let w = window();
        let (Ok(y), Some(h)) = (w.scroll_y(), w.inner_height().ok().and_then(|h| h.as_f64())) else { return };
        let total = document().document_element().map_or(0, |e| e.scroll_height());
        // Not after an error: each scroll event would ask again, against a rate limit too; the button retries.
        if f64::from(total) - y - h < 6.0 * h && next.with_untracked(Option::is_some) && error.with_untracked(Option::is_none) {
            load();
        }
    });
    on_cleanup(move || scroll.remove()); // a tab switch drops this timeline; its listener would keep loading it
    view! {
        // By place, as posts only ever append: each is cloned once, not the whole list again with every page.
        <For each=move || 0..posts.with(Vec::len) key=|i| *i let:i>
            {posts.with_untracked(|p| {
                let post = p[i].clone();
                let focal = which.with_value(|w| matches!(w, Timeline::Post(id) if *id == post.id));
                // The thread line runs on to the next post when it answers this one; from a post's page's own post, only to
                // its author's next post, not into someone else's reply.
                let threaded = p.get(i + 1).is_some_and(|n| {
                    n.reply_to.as_ref() == Some(&post.id) && (!focal || n.author.handle == post.author.handle)
                });
                view! { <PostView focal=focal threaded=threaded post=post /> }
            })}
        </For>
        {move || error.get().map(|e| view! { <p class="error">{e}</p> })}
        <button class="more" disabled=move || loading.get() on:click=move |_| load()>
            {move || if loading.get() { "Loading…" } else { "Load more" }}
        </button>
        <ViewerOverlay viewer=viewer />
    }
}

/// The photo open full size: a post's photos and which one shows. `None` when closed.
#[derive(Clone, Copy)]
struct Viewer(RwSignal<Option<(Vec<String>, usize)>>);

/// Photos at X's `large` size (2048 px at most); Escape or a click outside closes, the arrow keys step.
#[component]
fn ViewerOverlay(viewer: Viewer) -> impl IntoView {
    let step =
        move |by: isize| viewer.0.update(|v| v.iter_mut().for_each(|(urls, at)| *at = at.saturating_add_signed(by).min(urls.len() - 1)));
    let keys = window_event_listener(leptos::ev::keydown, move |e| match e.key().as_str() {
        _ if viewer.0.with_untracked(Option::is_none) => {}
        "Escape" => viewer.0.set(None),
        "ArrowLeft" => step(-1),
        "ArrowRight" => step(1),
        _ => {}
    });
    on_cleanup(move || keys.remove());
    move || {
        viewer.0.get().map(|(urls, at)| {
            let src = format!("{}?name=large", urls[at]);
            view! {
                <div class="viewer" on:click=move |_| viewer.0.set(None)>
                    <img src=src alt="" />
                    {(urls.len() > 1).then(|| view! { <span class="count">{format!("{} / {}", at + 1, urls.len())}</span> })}
                </div>
            }
        })
    }
}

/// One post. `focal` marks the post a post's page is about, `threaded` one the next post answers. A click anywhere in
/// it opens its page (`open`).
#[component]
fn PostView(post: Post, focal: bool, threaded: bool) -> impl IntoView {
    view! {
        <article class="post" class:focal=focal class:threaded=threaded data-page=page(&post)>
            {post.pinned.then(|| view! { <p class="repost pinned">"📌 Pinned"</p> })}
            {post.reposted_by.as_ref().map(|u| view! { <p class="repost">{format!("↻ {} reposted", u.name)}</p> })}
            <a class="author" href=format!("/{}", post.author.handle)>
                <img class="avatar" src=post.author.avatar.clone() alt="" loading="lazy" decoding="async" />
            </a>
            {content(&post, false)}
            {post.quote.as_deref().map(|q| view! { <div class="quote" data-page=page(q)>{content(q, true)}{counts(q)}</div> })}
            {counts(&post)}
        </article>
    }
}

fn counts(post: &Post) -> impl IntoView + use<> {
    view! {
        <p class="counts">
            <span class="replies">{format!("💬 {}", compact(post.replies))}</span>
            <span class="reposts">{format!("↻ {}", compact(post.reposts))}</span>
            <span class="likes">{format!("♥ {}", compact(post.likes))}</span>
            {post.views.map(|v| format!("👁 {}", compact(v)))} // no span: views take the row's own colour
        </p>
    }
}

/// A post's byline, text and media. The author's name opens their profile in kitter, the date the post's own page. A
/// quoted post has no avatar column, so its byline starts with a small avatar, as on X.
fn content(post: &Post, quoted: bool) -> impl IntoView + use<> {
    let user = &post.author;
    view! {
        <p class="byline">
            {quoted.then(|| view! { <img class="avatar small" src=user.avatar.clone() alt="" loading="lazy" decoding="async" /> })}
            <a class="name" href=format!("/{}", user.handle)>{user.name.clone()}</a>
            {format!(" @{} · ", user.handle)}
            <a class="when" href=page(post)>{short_date(&post.created_at)}</a>
        </p>
        <Text segments=post.text.clone() />
        <MediaGrid media=post.media.clone() />
    }
}

/// The tab's title. kitter names its pages as x.com does, so its tabs read as x.com's.
fn title(text: &str) { document().set_title(text); }

/// A post's text as plain words, for its page's title.
fn plain(segments: &[Segment]) -> String {
    segments
        .iter()
        .map(|s| match s {
            Segment::Text(t) => t.clone(),
            Segment::Link { shown, .. } => shown.clone(),
            Segment::Mention(h) => format!("@{h}"),
            Segment::Hashtag(t) => format!("#{t}"),
        })
        .collect()
}

/// A post's page in kitter, at the address x.com gives it.
fn page(post: &Post) -> String { format!("/{}/status/{}", post.author.handle, post.id) }

/// A click in a post opens its page, or the quoted post's when it lands in the quote: a plain page load, like
/// every link between kitter's pages. Not a click on a link, button, photo or video, which do their own thing,
/// nor one that ends a text selection.
#[allow(clippy::needless_pass_by_value)] // by value, as `window_event_listener` hands its event over
fn open(e: leptos::ev::MouseEvent) {
    let selecting = window().get_selection().ok().flatten().is_some_and(|s| !s.is_collapsed());
    let target = e.target().and_then(|t| t.dyn_into::<web_sys::Element>().ok()).filter(|_| !selecting);
    let page = target
        .filter(|t| t.closest("a, button, video, .media img").ok().flatten().is_none())
        .and_then(|t| t.closest("[data-page]").ok().flatten()?.get_attribute("data-page"));
    if let Some(page) = page {
        _ = window().location().set_href(&page);
    }
}

/// A post's text: links open in a new tab at their full address, mentions as kitter profiles, hashtags on
/// x.com itself.
#[component]
fn Text(segments: Vec<Segment>) -> impl IntoView {
    let parts = segments
        .into_iter()
        .map(|s| match s {
            Segment::Text(t) => t.into_any(),
            Segment::Link { shown, href } => view! { <a href=href target="_blank" rel="noopener noreferrer">{shown}</a> }.into_any(),
            Segment::Mention(h) => view! { <a class="mention" href=format!("/{h}")>{format!("@{h}")}</a> }.into_any(),
            Segment::Hashtag(t) =>
                view! { <a class="hashtag" href=format!("/hashtag/{}?krusta=off", encode(&t))>{format!("#{t}")}</a> }.into_any(),
        })
        .collect_view();
    view! { <p class="text">{parts}</p> }
}

/// A post's media laid out as X does: one at its own shape (capped in height), two side by side, three as one
/// tall and two stacked, four in a square. Photos load at X's `small` size (680 px wide at most) and open in
/// the viewer; videos load nothing until played; GIFs are muted loops that content.js plays only on screen.
#[component]
fn MediaGrid(media: Vec<Media>) -> impl IntoView {
    let viewer = expect_context::<Viewer>();
    let photos: Vec<String> = media.iter().filter(|m| m.kind == MediaKind::Photo).map(|m| m.url.clone()).collect();
    let count = media.len().min(4);
    let single_ratio = media.first().filter(|m| m.width > 0 && m.height > 0).map(|m| format!("{} / {}", m.width, m.height));
    (!media.is_empty()).then(|| {
        view! {
            <div class=format!("media n{count}") style:aspect-ratio=if count == 1 { single_ratio } else { None }>
                {media.into_iter().take(4).map(|m| {
                    let still = format!("{}?name=small", m.url);
                    match m.kind {
                        MediaKind::Video(src) => view! { <video src=src poster=still preload="none" controls playsinline></video> }.into_any(),
                        MediaKind::Gif(src) => view! { <video class="gif" src=src poster=still preload="none" prop:muted=true loop playsinline></video> }.into_any(),
                        MediaKind::Photo => {
                            let (photos, url) = (photos.clone(), m.url.clone());
                            let open = move |_| viewer.0.set(Some((photos.clone(), photos.iter().position(|p| *p == url).unwrap_or(0))));
                            view! { <img src=still alt="" loading="lazy" decoding="async" on:click=open /> }.into_any()
                        }
                    }
                }).collect_view()}
            </div>
        }
    })
}

#[wasm_bindgen]
extern "C" {
    /// content.js's fetch as the x.com page itself, so the request is same-origin and carries the session: of a
    /// path on x.com, which it refuses outside X's API. A GET when `body` is undefined. `catch`: a throw becomes an
    /// error the page shows; uncaught, it ended the task and left "Loading…" up.
    #[wasm_bindgen(js_name = krustaFetch, catch)]
    fn krusta_fetch(path: &str, body: Option<String>, headers: &str) -> Result<js_sys::Promise, JsValue>;
}

/// One call to x.com's API, its answer parsed. A wrapper so the generic part stays this line: each `T` copies it.
async fn fetch<T>(request: Request, parse: fn(&str) -> Result<T, kitter_api::Error>) -> Result<T, String> {
    parse(&send(request).await?).map_err(|e| e.to_string())
}

/// One call to x.com's API with the headers x.com's app sends, answered as text. The session is in the
/// cookies, which the browser adds; `ct0` is also the CSRF token X expects back as a header.
async fn send(request: Request) -> Result<String, String> {
    let csrf = cookie("ct0").ok_or("not signed in to x.com: no ct0 cookie")?;
    let headers = serde_json::json!({"authorization": kitter_api::BEARER, "content-type": "application/json", "x-csrf-token": csrf,
        "x-twitter-auth-type": "OAuth2Session", "x-twitter-active-user": "yes", "x-twitter-client-language": "en"});
    let sent = krusta_fetch(&request.path, request.body, &headers.to_string()).map_err(js_error)?;
    let response: Response = JsFuture::from(sent).await.map_err(js_error)?.unchecked_into();
    let text = JsFuture::from(response.text().map_err(js_error)?).await.map_err(js_error)?.as_string().unwrap_or_default();
    if !response.ok() {
        return Err(format!("x.com answered HTTP {}: {}", response.status(), text.chars().take(300).collect::<String>()));
    }
    Ok(text)
}

fn cookie(name: &str) -> Option<String> {
    let all = document().unchecked_into::<web_sys::HtmlDocument>().cookie().ok()?;
    all.split("; ").find_map(|pair| pair.strip_prefix(name)?.strip_prefix('=')).map(str::to_owned)
}

#[allow(clippy::needless_pass_by_value)] // by value so `map_err(js_error)` takes it as is
fn js_error(value: JsValue) -> String { value.as_string().unwrap_or_else(|| format!("{value:?}")) }

/// "Wed Oct 10 20:19:24 +0000 2018" as "Oct 10", with ", 2018" when that is not this year, as x.com shows it.
fn short_date(created_at: &str) -> String {
    let words: Vec<&str> = created_at.split(' ').collect();
    let (day, year) = (words.get(1..3).map(|d| d.join(" ")).unwrap_or_default(), words.last().copied().unwrap_or_default());
    if year == js_sys::Date::new_0().get_full_year().to_string() { day } else { format!("{day}, {year}") }
}

/// 1234 as "1.2K", 2500000 as "2.5M".
fn compact(n: u64) -> String {
    #[allow(clippy::cast_precision_loss)] // counts this large are shown to one decimal anyway
    let f = n as f64;
    match n {
        0..1_000 => n.to_string(),
        1_000..1_000_000 => format!("{:.1}K", f / 1e3),
        _ => format!("{:.1}M", f / 1e6),
    }
}
