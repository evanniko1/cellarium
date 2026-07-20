# Cellarium-authored skills

These publication/rigor Agent Skills are **authored for this project** — they are NOT vendored from K-Dense
or any external source, and carry no third-party attribution. They exist to encode Cellarium's own manuscript
conventions and to route the writing/review/uncertainty workflow through the toolkit's *own* executable rigor
tools (`stats`, `rigor`, `robustness`, `provenance`, `power_check`, the biosecurity screen, the blindness control).

They are loaded by the same `use_skill` / `skills.load_skill` machinery as the vendored K-Dense literature skills
(`skills/vendor/k-dense/`, see that directory's `ATTRIBUTION.md` / `LICENSE.md`), but live under `skills/cellarium/`
so provenance is unambiguous: vendored literature skills fetch external APIs via `web_get`; these Cellarium skills
point the agent at this project's own grounded tools and conventions.

Generic third-party publication skills (K-Dense `citation-management`/`pyzotero`, `scientific-visualization`,
`slides`, `latex-posters`) can be vendored under `skills/vendor/` later, faithfully, when their sources are on hand;
they are intentionally not reproduced here.
