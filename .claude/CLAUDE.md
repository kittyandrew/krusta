# krusta

A Firefox (Zen) extension that drops some sites' own apps and draws its own interfaces, Leptos clients compiled to
WebAssembly, on the browser's existing sessions. A shell shared by every site (`extension/`) and a folder per site
(`sites/<id>/`); so far X, whose interface is kitter. AGPL-3.0 (`LICENSE`).

- `docs/design.md` holds every design decision, how to add a site, and how kitter talks to X. Read it before
  changing behaviour, and update it in the same change.
- `.claude/rules/` is the operating manual, loaded every session: `001-architecture.md` for the parts,
  `002-dev.md` for the gates, tests and style, `003-vocabulary.md` for labelling who does a step,
  `004-zen.md` for live checks and the bench in a Zen of krusta's own.
- Research behind the project (X's APIs, existing clients, GPUI, the kubicle approach) is in
  `~/.local/state/x-client-research/README.md`, outside the repo.
