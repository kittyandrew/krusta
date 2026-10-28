// Installed beside kitter by budgets.py, which reads the mark: the time from the navigation's start until the first
// post is in the page and laid out. A content script, since only one runs before kitter's client starts drawing.
new MutationObserver((_, observer) => {
  if (!document.querySelector(".post")) return
  document.body.getBoundingClientRect() // forces the layout, as kubicle's budgets do before they read the clock
  document.documentElement.dataset.firstPost = String(performance.now())
  observer.disconnect()
}).observe(document, { childList: true, subtree: true })
