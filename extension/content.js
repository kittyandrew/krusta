// Draws this site's client (background.js registers this script, after sites.js, on each site's hosts)
// in place of the site's page, unless ?krusta=off asked for the site or the page is one of its sign-in pages.
const site = SITES.find((s) => s.hosts.includes(location.hostname))
if (new URLSearchParams(location.search).get("krusta") !== "off" && !new RegExp(site.signIn).test(location.pathname)) {
  // At document_start nothing of the site's page has run: stopping the load aborts its parser, so none of its HTML
  // or scripts follow, and krusta gets an empty page of its own. Not webRequest.filterResponseData: Zen answers
  // it "Invalid request ID" on most loads and lets x.com's HTML through (Oct 27, 2026).
  window.stop()
  document.documentElement.replaceChildren(document.createElement("head"), document.createElement("body"))
  // The site's own icon, at the address browsers look for one; the interface sets the title.
  const icon = document.createElement("link")
  icon.rel = "icon"
  icon.href = "/favicon.ico"
  document.head.append(icon)

  // In a Manifest V3 content script, Firefox sends fetch with the page's origin: the request is the site's own,
  // same-origin, with its cookies. (MV2's `content.fetch` for this does not exist in MV3.) It sends only a path that,
  // resolved on this origin (`..` too), lies under the site's API, site.json's `api`: the headers carry the CSRF token.
  globalThis.krustaFetch = (path, body, headers) => {
    const url = new URL(path, location.origin)
    if (url.origin !== location.origin || !url.pathname.startsWith(site.api)) throw new Error(`krustaFetch refuses ${path}`)
    return fetch(url, { method: body === undefined ? "GET" : "POST", body, headers: JSON.parse(headers), credentials: "include" })
  }

  // A client's looping video (`video.gif`; GIFs are MP4s on X) plays only while on screen, so a long feed never
  // decodes dozens of loops at once. Observing a video already observed does nothing, so each change observes all.
  const onScreen = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) e.target.play().catch(() => {})
      else e.target.pause()
    }
  })
  new MutationObserver(() => {
    for (const v of document.querySelectorAll("video.gif")) onScreen.observe(v)
  }).observe(document, { childList: true, subtree: true })

  const own = (file) => browser.runtime.getURL(`sites/${site.id}/${file}`)
  const css = document.createElement("link")
  css.rel = "stylesheet"
  // A new address each load: Firefox keeps a stylesheet by address, and an updated or reloaded add-on keeps its
  // moz-extension address, so tabs drew the old stylesheet until the browser restarted (Oct 27, 2026).
  css.href = `${own("style.css")}?${Date.now()}`
  document.head.append(css)
  import(own("client.js")).then(async (client) => {
    await client.default({ module_or_path: own("client_bg.wasm") })
    client.start()
  })
}
