// krusta's shell for every site in SITES (sites.js: each sites/<id>/site.json). content.js draws the interface in a
// site's tab; here the site's own app is kept out of it: its service worker blocked, its CSP dropped. A page opened
// with ?krusta=off, or a sign-in page, stays the site's. Nothing is kept per tab: Firefox stops this event page after
// 30 s idle, which would lose it. The toolbar button turns krusta off and on per interface.
const off = new Set() // ids of the interfaces turned off with the button
const pages = (site) => site.hosts.map((host) => `https://${host}/*`)
const siteOf = (url) => {
  const host = new URL(url).hostname
  return SITES.find((site) => site.hosts.includes(host) || site.appScripts.some((prefix) => url.startsWith(prefix)))
}
// A page the site keeps, told as content.js tells it.
const kept = (url, site) => url.searchParams.get("krusta") === "off" || new RegExp(site.signIn).test(url.pathname)

// One registered content script per site that is on, under the site's id; off, the site's tabs are its own, but for
// its service worker (below). The choice is stored, so it outlasts this event page, which Firefox stops when idle,
// and the browser; a registration no site wants, from a site since removed, goes too.
const sync = async () => {
  const registered = (await browser.scripting.getRegisteredContentScripts()).map((script) => script.id)
  const wanted = SITES.filter((site) => !off.has(site.id))
  const stale = registered.filter((id) => !wanted.some((site) => site.id === id))
  if (stale.length) await browser.scripting.unregisterContentScripts({ ids: stale })
  const missing = wanted.filter((site) => !registered.includes(site.id))
  const script = (site) => ({ id: site.id, matches: pages(site), js: ["sites.js", "content.js"], runAt: "document_start" })
  if (missing.length) await browser.scripting.registerContentScripts(missing.map(script))
}
const loaded = browser.storage.local.get({ off: [] }).then((stored) => {
  for (const id of stored.off) off.add(id)
  return sync()
})

// The button's icon, badge and title in one tab: the pink-to-teal mark while on, lavender and a red "off" while the
// tab's site is off. A tab on no site has no address this add-on may read.
const mark = (tabId, url) => {
  const site = url && siteOf(url)
  const state = site && (off.has(site.id) ? "off" : "on")
  browser.action.setIcon({ tabId, path: state === "off" ? "icon-off.svg" : "icon-on.svg" })
  browser.action.setBadgeText({ tabId, text: state === "off" ? "off" : "" }) // in Frappe's red, set below
  browser.action.setTitle({ tabId, title: site ? `${site.id}: ${state}. Click to switch` : "krusta: not for this site" })
}
browser.action.setBadgeBackgroundColor({ color: "#e78284" })
browser.action.setBadgeTextColor({ color: "#303446" })
// Zen also reports updates of a tab -1, which no tab call takes.
const marked = (tabId, _, tab) => tabId >= 0 && loaded.then(() => mark(tabId, tab.url))
browser.tabs.onUpdated.addListener(marked, { properties: ["url", "status"] })
browser.action.onClicked.addListener(async (clicked) => {
  await loaded
  // Zen passes no tab when the button sits in its extensions menu: the active tab is the one it was clicked over.
  const tab = clicked ?? (await browser.tabs.query({ active: true, lastFocusedWindow: true }))[0]
  const site = tab?.url && siteOf(tab.url)
  if (!site) return
  if (off.has(site.id)) off.delete(site.id)
  else off.add(site.id)
  await browser.storage.local.set({ off: [...off] })
  await sync()
  await browser.tabs.reload(tab.id)
})

// A site's service worker answers its pages and app from its own cache, so they never reach the network and the
// handlers below: its app then starts from cache in a krusta tab. Remove it; the handler below keeps it out.
const dropServiceWorkers = () =>
  browser.browsingData.remove({ hostnames: SITES.flatMap((site) => site.hosts) }, { serviceWorkers: true })
browser.runtime.onStartup.addListener(dropServiceWorkers)
// An update or reinstall (Zen's policy reinstalls krusta when its build changes) nukes the content scripts of open
// tabs: their pages stay drawn but stop paging and answering clicks. Load them again once content.js is registered,
// which an update clears.
browser.runtime.onInstalled.addListener(async () => {
  dropServiceWorkers()
  await loaded
  for (const tab of await browser.tabs.query({ url: SITES.flatMap(pages), discarded: false })) browser.tabs.reload(tab.id)
})

// The service worker's scripts, which Firefox loads with no tab (tabId -1), from every tab and with a site turned off
// too (sites/kitter/tests/vm.nix). A tab's own pass: content.js stops a krusta tab's page before it asks for any.
browser.webRequest.onBeforeRequest.addListener(
  (request) => ({ cancel: request.tabId === -1 }),
  { urls: SITES.flatMap((site) => [...pages(site), ...site.appScripts.map((prefix) => `${prefix}*`)]), types: ["script"] },
  ["blocking"]
)

// A site's Content-Security-Policy would keep the page from loading the client's stylesheet; krusta is the page now.
browser.webRequest.onHeadersReceived.addListener(
  async (response) => {
    await loaded
    const site = siteOf(response.url)
    if (off.has(site.id) || kept(new URL(response.url), site)) return {}
    return { responseHeaders: response.responseHeaders.filter((h) => h.name.toLowerCase() !== "content-security-policy") }
  },
  { urls: SITES.flatMap(pages), types: ["main_frame"] },
  ["blocking", "responseHeaders"]
)
