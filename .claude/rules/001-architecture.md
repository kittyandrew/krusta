# Architecture

One add-on, krusta, with a shell shared by every site and a folder per interface. Per tab, one direction:
the shell prepares the tab, the interface draws and asks, the site answers. So far one: kitter, for X
(`sites/kitter/`).

- **`extension/`**: the shell, a Firefox MV3 add-on. The build (`nix/package.nix`) adds `sites.js` (every
  `site.json` as `SITES`, each with its folder's name as `id`), each interface's client and stylesheet under
  `sites/<id>/`, and the manifest's per-site host permissions and resources.
  - `content.js` stops the site's page at `document_start` (`window.stop()`), empties it, loads the interface's
    client there and gives it `krustaFetch`: the content script's `fetch`, which Firefox sends in MV3 with the
    page's origin, so it carries the site's session. It takes a path and sends only one under `site.json`'s `api`.
    Never `webRequest.filterResponseData`: Zen fails it on most loads.
  - `background.js` registers `content.js` per interface that is on and drops the page's Content-Security-Policy,
    but not on the site's sign-in pages or a page opened with `?krusta=off`. It removes the sites' service workers
    at install and startup and cancels every script with no tab: a worker serves the site's app from cache, past
    every other handler. After an install or update it reloads the sites' open tabs, whose content scripts Firefox
    killed. It keeps nothing per tab, since Firefox stops it after 30 s idle. Its toolbar button turns krusta off
    and on for the clicked tab's interface and reloads that tab; the choice is in `storage.local`.
- **`sites/<id>/`**: everything about one interface, its folder named after it. Adding one: `docs/design.md`.
  - `site.json`: the site's hosts, sign-in paths, API path and app scripts, for the shell and the build.
  - `api/`, crate `<id>-api`: the site's web API and its parsers, with no browser dependency.
  - `web/`, crate `<id>-web`: the Leptos client; exports `start()`. Built to its own wasm.
  - `style.css`, and `tests/`: its VM suite (`vm.nix`, flake check `vm-<id>`) and anything measured live.
- **kitter**: `sites/kitter/api` builds each call to X from `src/graphql.json` (query ids, feature switches) and
  parses the answers, walking the JSON rather than fixed structs, since X moves fields often. The parsers check
  every handle, id, link and banner, which end up in paths, links and CSS (docs/design.md, Talking to X).
  `sites/kitter/web` draws a page by its path: docs/design.md, How a tab becomes kitter.

## Contracts

- An interface never stores or sends the session itself: the browser adds the cookies. kitter reads only `ct0`,
  to send back as `x-csrf-token`, as x.com's app does.
- No shared Rust crate until a second interface shows what it shares (Andrew, Oct 28, 2026): the shell is the
  shared part.
- kitter's `graphql.json` mirrors x.com's current bundle. When X answers 400, 404 or error 336, refresh that
  call's entry from fa0311/TwitterInternalAPIDocument's `docs/json/GraphQL.json` and record the date in
  `sites/kitter/api`.
- `wasm-bindgen` is pinned to nixpkgs' `wasm-bindgen-cli` version: bump both together.
