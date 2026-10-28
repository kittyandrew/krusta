// Starts as soon as run.sh installs the add-on: x.com/home ROUNDS times as kitter and as x.com's own app,
// alternating, in one new tab, then the medians and every run as kitter-bench-<time>.json in the downloads folder.
// Then MEMORY_ROUNDS times one tab of each, measured the same way and left open while memory.py dumps Zen's
// memory and reads both tabs from it. MV2's persistent background: an MV3 one may be suspended in a wait.
const ROUNDS = 5
const MEMORY_ROUNDS = 3
const DUMP_WAIT = 30000 // the time memory.py has for its dump before the two tabs close
const URLS = { kitter: "https://x.com/home?bench=1", "x.com": "https://x.com/home?krusta=off&bench=1" }
let measured = () => {}
browser.runtime.onMessage.addListener((message) => measured(message))

const load = (tabId, url) =>
  new Promise((resolve, reject) => {
    const late = setTimeout(async () => {
      const tab = await browser.tabs.get(tabId)
      reject(new Error(`no measurement from ${url} within 60 s; the tab is ${tab.status} at ${tab.url}: ${tab.title}`))
    }, 60000)
    measured = (message) => {
      clearTimeout(late)
      if (message.stuck === undefined) resolve(message)
      else reject(new Error(`no post from ${url} within 30 s; the page shows: ${message.stuck}`))
    }
    browser.tabs.update(tabId, { url })
  })

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.floor(sorted.length / 2)]
}

const save = (name, data) => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }))
  return browser.downloads.download({ url, filename: name, saveAs: false }).then(() => url)
}

// One tab per app with the same load and scroll, then their addresses for memory.py, which finds each tab in the
// dump by its address: x.com's app keeps the query, so `memory` tells the rounds apart.
const memoryRound = async (round) => {
  const tabs = []
  const urls = {}
  for (const app of Object.keys(URLS)) {
    urls[app] = `${URLS[app]}&memory=${round}`
    const tab = await browser.tabs.create({ url: "about:blank", active: true })
    tabs.push(tab.id)
    await load(tab.id, urls[app])
  }
  await save(`kitter-bench-memory-ready-${Date.now()}.json`, { round, urls })
  await new Promise((resolve) => setTimeout(resolve, DUMP_WAIT))
  await browser.tabs.remove(tabs)
}

browser.runtime.onInstalled.addListener(async () => {
  const tab = await browser.tabs.create({ url: "about:blank", active: true })
  const runs = []
  let error = null
  try {
    for (let round = 0; round < ROUNDS; round++) {
      for (const app of round % 2 ? ["x.com", "kitter"] : ["kitter", "x.com"]) runs.push(await load(tab.id, URLS[app]))
    }
    for (let round = 0; round < MEMORY_ROUNDS; round++) await memoryRound(round)
  } catch (e) {
    error = String(e)
  }
  const metrics = Object.keys(runs[0] ?? {}).filter((k) => k !== "app")
  const summary = Object.fromEntries(
    Object.keys(URLS).map((app) => {
      const own = runs.filter((r) => r.app === app)
      return [app, Object.fromEntries(metrics.map((m) => [m, median(own.map((r) => r[m]))]))]
    })
  )
  const report = { date: new Date().toISOString(), userAgent: navigator.userAgent, rounds: ROUNDS, error, summary, runs }
  browser.tabs.update(tab.id, { url: await save(`kitter-bench-${Date.now()}.json`, report) })
})
