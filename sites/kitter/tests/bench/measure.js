// One measurement in the bench's tab (?bench=1), the same for x.com's app (?krusta=off) and for kitter: the time to
// the first post, a quick scroll through the feed, then what the page holds. background.js collects it.
const query = new URLSearchParams(location.search)
if (query.has("bench")) {
  const app = query.get("krusta") === "off" ? "x.com" : "kitter"
  const POST = app === "x.com" ? 'article[data-testid="tweet"]' : "article.post"
  const STEP = 80 // pixels a frame for 300 frames: 4,800 px/s for 5 s at 60 frames a second, as the speed measurements scroll
  const FRAMES = 300
  const frame = () => new Promise(requestAnimationFrame)
  const scroll = async () => {
    const gaps = []
    let last = await frame()
    for (let i = 0; i < FRAMES; i++) {
      window.scrollBy(0, STEP)
      const now = await frame()
      gaps.push(now - last)
      last = now
    }
    return gaps
  }
  // No post in 30 s: what the page shows instead (kitter's error, x.com's sign-in), for background.js's report.
  const stuck = setTimeout(() => browser.runtime.sendMessage({ app, stuck: document.body?.innerText.slice(0, 300) ?? "" }), 30000)
  new MutationObserver((_, observer) => {
    if (!document.querySelector(POST)) return
    observer.disconnect()
    clearTimeout(stuck)
    document.body.getBoundingClientRect() // the post laid out, as the speed measurements read it
    const firstPost = performance.now() // from the navigation's start
    // Two seconds for the first screen's images and the app's own start-up work before the scroll.
    setTimeout(async () => {
      const gaps = await scroll()
      browser.runtime.sendMessage({
        app,
        firstPostMs: firstPost,
        worstFrameMs: Math.max(...gaps),
        framesOver50Ms: gaps.filter((g) => g > 50).length,
        scrolledPx: window.scrollY, // short of 24,000 when the feed's end held the scroll
        postsInPage: document.querySelectorAll(POST).length,
        elements: document.getElementsByTagName("*").length
      })
    }, 2000)
  }).observe(document, { childList: true, subtree: true })
}
