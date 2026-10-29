# krusta

Fast interfaces that replace some sites' own apps in your Firefox tab, on the sessions you are already signed in
with. A toolbar button switches krusta off and on per site.

Interfaces so far:

- **kitter**, for X (`sites/kitter/`): the home page (For You, Following and your pinned lists and communities),
  profiles with their Posts, Replies and Media tabs, and a post's own page with its thread and replies. It calls
  X's web API as x.com's own app does, which X's terms of service do not allow: your account carries that risk.

```bash
nix build .#extension   # unpacked add-on: load its manifest.json in about:debugging, "Load Temporary Add-on"
nix build .#xpi         # the same, zipped
```

Design, and how to add an interface: `docs/design.md`. License: AGPL-3.0 (`LICENSE`).
