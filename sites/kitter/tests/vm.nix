# vm-kitter: kitter on X in a real Firefox against the fake X (fixture/), through the scenarios in scenarios.py.
# `.plants` boots six VMs side by side; each runs, after the clean build, its share of the planted bugs' scenarios
# against a build with that bug, swapping the .xpi Firefox installs. It passes only when every plant fails each
# scenario it names. A plant whose patch no longer applies fails the build, which says to update the plant.
{
  pkgs,
  krusta,
}: let
  inherit (pkgs) lib;
  judge = import ../../../tests/judge.nix {inherit pkgs;};
  fixture = import ./fixture {inherit pkgs;};

  # Developer Edition, as release Firefox installs only signed add-ons and the .xpi is unsigned.
  firefox = pkgs.wrapFirefox pkgs.firefox-devedition-unwrapped {
    extraPolicies = {
      Certificates.Install = ["${fixture.tls}/ca.pem"];
      # Each new session's fresh profile installs whichever build /run/krusta.xpi links to.
      ExtensionSettings."krusta@kittyandrew" = {
        installation_mode = "force_installed";
        install_url = "file:///run/krusta.xpi";
      };
    };
    extraPrefs = ''
      lockPref("xpinstall.signatures.required", false);
      // Console messages of pages and add-ons on stdout, which geckodriver writes to the journal.
      pref("devtools.console.stdout.content", true);
      pref("devtools.console.stdout.chrome", true);
      // Firefox stops an idle event page after 30 s; 2 s here, so every scenario runs across those stops.
      pref("extensions.background.idle.timeout", 2000);
    '';
  };

  patched = drv: patch: drv.overrideAttrs (old: {postPatch = (old.postPatch or "") + patch;});
  # The add-on with `web` patched into the client's source tree and `extension` run in the add-on's folder.
  plantXpi = {
    web ? "",
    extension ? "",
    ...
  }: let
    client =
      if web == ""
      then krusta.clients.kitter
      else patched krusta.clients.kitter web;
  in
    pkgs.runCommand "krusta-plant.xpi" {nativeBuildInputs = [pkgs.zip];} ''
      cp -r ${krusta.extension} ext && chmod -R u+w ext && cd ext
      cp ${client}/client.js ${client}/client_bg.wasm sites/kitter/
      ${extension}
      zip -qrX $out .
    '';
  # The planted bugs (.claude/rules/002-dev.md, Tests): each the scenario it must fail and the text it replaces, in
  # the client's source (`web`, and `api`: kitter-api, which the client build compiles in) or in a file of the add-on.
  plants = let
    plant = kind: file: scenario: from: to: {
      scenarios = [scenario];
      ${kind} = "substituteInPlace ${file} --replace-fail ${lib.escapeShellArg from} ${lib.escapeShellArg to}";
    };
    web = plant "web" "sites/kitter/web/src/lib.rs";
    api = plant "web" "sites/kitter/api/src/lib.rs";
    ext = plant "extension";
  in {
    page-kept = ext "content.js" "takeover" "window.stop()" "";
    css-unreachable = ext "manifest.json" "takeover" ''"sites/kitter/style.css"'' ''"sites/kitter/gone.css"'';
    # The bundle handler stops seeing scripts. A krusta tab still asks for none (content.js stops its page), but
    # x.com itself (?krusta=off) then registers its service worker, whose script has no tab and only this
    # handler cancels; the worker would then serve X's app to krusta tabs.
    scripts-unblocked = ext "background.js" "krusta-off" ''types: ["script"]'' ''types: ["main_frame"]'';
    off-forgotten = ext "content.js" "krusta-off" ''.get("krusta") !== "off"'' ''.get("krusta") !== "of"'';
    csrf-renamed = web "feed" ''"x-csrf-token": csrf'' ''"x-csrftoken": csrf'';
    counts-swapped = web "feed" ''format!("↻ {}", compact(post.reposts))'' ''format!("↻ {}", compact(post.likes))'';
    cursor-dropped = web "scroll" "cursor.as_deref()" "None";
    three-unplaced = ext "sites/kitter/style.css" "layouts" "grid-area: a;" "";
    grid-capped = web "layouts" "media.len().min(4)" "media.len().min(3)";
    escape-ignored = web "viewer" ''"Escape" => viewer.0.set(None),'' ''"Esc" => viewer.0.set(None),'';
    video-preloads = web "video" ''preload="none" controls'' ''preload="auto" controls'';
    gif-always-plays = ext "content.js" "gif" "else e.target.pause()" "else e.target.play().catch(() => {})";
    mention-off-kitter = web "links" ''format!("/{h}")'' ''format!("/{h}?krusta=off")'';
    following-is-for-you = api "tabs" ''Timeline::Following => ("HomeLatestTimeline"'' ''Timeline::Following => ("HomeTimeline"'';
    lists-unpinned = api "tabs" ''"ListPinnedTimeline" =>'' ''"List" =>'';
    communities-unpinned = api "tabs" ''"CommunityPinnedTimeline" =>'' ''"Community" =>'';
    pin-dropped = api "profile" "Post { pinned, ..p }" "Post { pinned: false, ..p }";
    follows-swapped = web "profile" ''compact(following)}</b>" Following"'' ''compact(followers)}</b>" Following"'';
    # Every call a POST: X answers a GET-only call sent so with 404, so no profile shows.
    gets-posted = api "profile" ''if operation.starts_with("Home")'' "if !operation.is_empty()";
    settings-as-profile = web "profile" ''"settings",'' ''"settingz",'';
    media-link-shown = api "links" ''list("media")'' ''list("no-media")'';
    # X's own fields taken as they come: a javascript: link, a mention and an author whose handle leads to //kitter.test.
    link-any-scheme = api "links" ''u.starts_with("https://") || u.starts_with("http://")'' "!u.is_empty()";
    handle-unchecked = api "links" ".filter(|h| is_handle(h))" "";
    # krustaFetch sends any path on x.com, past X's API, with the client's CSRF header.
    fetch-any-path = ext "content.js" "api-only" "!url.pathname.startsWith(site.api)" "false";
    # The toolbar button turns krusta off for kitter, but content.js still draws kitter in every tab.
    button-keeps-kitter = ext "background.js" "toggle" "await browser.scripting.unregisterContentScripts({ ids: stale })" "null";
    button-no-reload = ext "background.js" "toggle" "await browser.tabs.reload(tab.id)" "null";
    # Off lets every script through, x.com's service worker too, which would then serve X's app once krusta is on.
    worker-when-off = ext "background.js" "toggle" "cancel: request.tabId === -1" "cancel: false";
    replies-are-posts = api "profile-tabs" ''"UserTweetsAndReplies",'' ''"UserTweets",'';
    media-tab-missing = web "profile-tabs" ''("Media".into(), Timeline::Media(id)),'' "";
    post-click-ignored = web "post" "window_event_listener(leptos::ev::click, open);" "";
    # A click in a quote then opens the post around it instead of the quoted one.
    quote-opens-outer = web "post" ''<div class="quote" data-page=page(q)>'' ''<div class="quote">'';
    focal-unmarked = web "post" "class:focal=focal" "class:focal=false";
    discover-more-shown = api "post" ''"tweetdetailrelatedtweets-"'' ''"never-"'';
    title-unset = web "takeover" "fn title(text: &str) { document().set_title(text); }" "fn title(_: &str) {}";
    icon-missing = ext "content.js" "takeover" ''icon.href = "/favicon.ico"'' ''icon.href = "/favicon.png"'';
    profile-title-swapped = web "profile" "p.user.name, p.user.handle" "p.user.handle, p.user.name";
    post-title-id = web "post" "plain(&post.text)" "post.id";
    quote-uncounted = web "post" "{content(q, true)}{counts(q, toast)}" "{content(q, true)}";
    bar-tabless = web "post" "{tab_bar(tabs, tab)}" "";
    # A home tab on another page then opens For You, whichever was clicked.
    tab-forgotten = web "post" ''&format!("/home#{}", tab_key(&which))'' ''"/home"'';
    thread-unmarked = web "thread" "class:threaded=threaded" "class:threaded=false";
    thread-from-focal = web "thread" "(!focal || n.author.handle == post.author.handle)" "!focal";
    thread-undrawn = ext "sites/kitter/style.css" "thread" ''content: "";'' "";
    detail-unasked = api "post" ''"focalTweetId": id'' ''"tweetId": id'';
    # The quoted post's avatar outside its name's link: a click on it then opens the quoted post, not its author.
    quote-avatar-unlinked = web "post" ">{picture}{user.name.clone()}</a>" ">{user.name.clone()}</a>{picture}";
    repost-faceless = web "repost" "{author(&r.by, true)}" "{author(&r.by, false)}";
    repost-time-original = api "repost" "Repost { by: author, created_at }" ''Repost { by: author, created_at: original["legacy"]["created_at"].as_str().unwrap_or_default().into() }'';
    gold-as-blue = api "badges" ''Some("Business") => Some(Badge::Gold),'' ''Some("Business") => Some(Badge::Blue),'';
    affiliates-dropped = api "badges" ''affiliate: affiliate(&result["affiliates_highlighted_label"]["label"]),'' "affiliate: None,";
    badge-undrawn = ext "sites/kitter/style.css" "badges" ''[data-badge="gold"]::after {'' ''[data-badge="golden"]::after {'';
    language-fixed = web "badges" ''cookie("lang").unwrap_or_else(|| "en".into())'' ''String::from("en")'';
    bio-unmentioned = api "profile" ''&bio["entities"]["description"], None, true)'' ''&bio["entities"]["description"], None, false)'';
    mention-in-address = api "profile" ''!(word(chars[i - 1]) || "!#$%&*@".contains(chars[i - 1]))'' "true";
    translation-dropped = api "translation" ''translation: translation(&tweet["grok_translated_post_with_availability"]),'' "translation: None,";
    translation-unlinked = api "translation" ''split(data["translation"].as_str()?, &data["entities"], None, false)'' ''split(data["translation"].as_str()?, &Value::Null, None, false)'';
    original-first = web "translation" "let translated = RwSignal::new(true);" "let translated = RwSignal::new(false);";
    translation-stuck = web "translation" "translated.update(|t| *t = !*t)" "translated.update(|t| *t = true)";
    # The bug Andrew met: a post with no replies still offered "Load more", and the end of any timeline too.
    more-past-end = web "load-more" "next.with(|n| *n != Next::End)" "next.with(|_| true)";
    discover-more-paged = api "load-more" "!past_replies && " "";
    # A share button copying anything but the post's own address on x.com: the address alone, the page's, one by the
    # author's name, the reposter's, or the outer post's from a quote.
    share-relative = web "share" ''format!("https://x.com{}", page(post))'' "page(post)";
    share-page-address = web "share" ''format!("https://x.com{}", page(post))'' "window().location().href().unwrap_or_default()";
    share-by-name = web "share" ''format!("/{}/status/{}", post.author.handle, post.id)'' ''format!("/{}/status/{}", post.author.name, post.id)'';
    share-reposter = api "share" "return Some(Post { repost: Some(" "return Some(Post { author: author.clone(), repost: Some(";
    share-quote-outer = web "share" "{counts(q, toast)}" "{counts(&post, toast)}";
    share-untabbable = web "share" ''<button class="share"'' ''<button class="share" tabindex="-1"'';
    # The page's click listener taking the button for the post around it: the click copies, then opens the post.
    share-opens-post = web "share" ''t.closest("a, button, video, .media img")'' ''t.closest("a, video, .media img")'';
    share-unconfirmed = web "share" ''"Copied to clipboard"'' ''""'';
    toast-stays = web "share" "Duration::from_secs(3)" "Duration::from_secs(30)";
    toast-unannounced = web "share" ''<p class="toast" role="status">'' ''<p class="toast">'';
    # The bug that happened live: a throw ended the request's task, and the button said it was loading for good.
    error-throws = web "api-error" "Err(e) => error.set(Some(e))," "Err(e) => wasm_bindgen::throw_str(&e),";
    retries-on-scroll = web "rate-limit" "error.with_untracked(Option::is_none) && " "";
    past-end-followed = api "timeline-end" " && !page.posts.is_empty()" "";
    update-leaves-tabs = ext "background.js" "update" "discarded: false })) browser.tabs.reload(tab.id)" "discarded: false })) void tab";
    # Tabs kept in the event page, which Firefox stops when idle: a sign-in tab's next script is then cancelled.
    tab-remembered = {
      scenarios = ["sign-in-idle"];
      extension = ''
        substituteInPlace background.js --replace-fail ${lib.escapeShellArg ''types: ["script"]''} ${lib.escapeShellArg ''types: ["main_frame", "script"]''} \
          --replace-fail ${lib.escapeShellArg "(request) => ({ cancel: request.tabId === -1 })"} \
          ${lib.escapeShellArg ''(request) => request.type === "main_frame" ? void (globalThis.seen ??= new Set()).add(request.tabId) : { cancel: request.tabId === -1 || !globalThis.seen?.has(request.tabId) }''}
      '';
    };
  };

  run = name: planted:
    judge (pkgs.testers.runNixOSTest {
      inherit name;
      extraPythonPackages = p: [p.selenium];
      nodes.machine = {
        imports = [fixture.module];
        virtualisation = {
          memorySize = 2048;
          cores = 2;
        };
        fonts.enableDefaultPackages = true; # else every glyph is a fallback box and text measures differently
        users.users.browser = {
          isSystemUser = true;
          group = "browser";
          home = "/var/lib/browser";
          createHome = true;
        };
        users.groups.browser = {};
        systemd.tmpfiles.rules =
          ["L+ /run/krusta.xpi - - - - ${krusta.xpi}"]
          ++ lib.mapAttrsToList (plant: p: "L+ /run/krusta-plants/${plant}.xpi - - - - ${plantXpi p}") planted;
        # Selenium on the host reaches it through a port forwarded from the host's loopback, which the test picks
        # free at run time and starts this unit on: geckodriver refuses a Host header whose port is not its own.
        # --allow-system-access opens the browser's own window to the test, for krusta's toolbar button.
        systemd.services."geckodriver@" = {
          environment = {
            HOME = "/var/lib/browser";
            MOZ_LOG = "timestamp,nsHttp:3"; # every request's and answer's headers: Firefox's network log
            MOZ_LOG_FILE = "/var/log/firefox/http";
          };
          serviceConfig = {
            ExecStart = "${lib.getExe pkgs.geckodriver} --host 0.0.0.0 --port %i --allow-hosts 127.0.0.1 --allow-system-access --binary ${firefox}/bin/firefox-devedition";
            User = "browser";
            LogsDirectory = "firefox";
          };
        };
        networking.firewall.enable = false; # for that port
      };
      testScript =
        builtins.readFile ../../../tests/record.py
        + builtins.readFile ./scenarios.py
        + ''
          run_feed(${builtins.toJSON (builtins.toJSON (lib.mapAttrs (_: p: p.scenarios) planted))})
        '';
    });
  # The plants dealt round-robin to six VMs, which Nix runs side by side (2 cores and 2 GB each): a caught plant
  # mostly waits out its scenario's timeout, so one VM took 380 s for 31 plants; six took 60 to 80 s (Oct 28, 2026).
  dealt = lib.imap0 (i: name: {
    inherit name;
    part = lib.mod i 6;
  }) (lib.attrNames plants);
  parts = lib.listToAttrs (lib.genList (part:
    lib.nameValuePair "p${toString part}"
    (run "krusta-vm-kitter-plants-p${toString part}" (lib.getAttrs (map (d: d.name) (lib.filter (d: d.part == part) dealt)) plants)))
  6);
in
  # .plants fails when any part does; a part's evidence is `.plants.parts.p0.run` and so on. `.fixture` is for the
  # speed measurements (budgets/run.sh), which take its recording and certificate.
  run "krusta-vm-kitter" {}
  // {
    plants = pkgs.linkFarmFromDrvs "krusta-vm-kitter-plants" (lib.attrValues parts) // {inherit parts;};
    inherit fixture;
  }
