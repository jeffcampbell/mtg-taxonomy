# CLAUDE.md — scry

Token-efficient Magic card data for AI agents: Scryfall lookups plus deck themes for
every card. Stdlib-only Python for users; keep it that way (decide is an optional,
maintainer-only import). User docs, methodology and known gaps: `README.md`. Output
compactness is the product: measure before adding anything to the default output.

## Layout (`src/scry/`)

| Module | Role |
|---|---|
| `api.py` | Scryfall GET: required headers, per-endpoint spacing, shared 429 cooldown file. |
| `db.py` | Bulk oracle file → trimmed JSON in SQLite (`cards`, `names` aliases ranked real-before-token). `norm()` is the lookup key. |
| `lookup.py` | Name resolution: exact → prefix → local close match → API fuzzy (similarity-checked). |
| `render.py` | Card → text. The output format is documented in its docstring and README. |
| `deck.py` | Archidekt API and text deck lists → `(qty, name, section)`. |
| `cli.py` | argparse + commands. Results to stdout; staleness/progress to stderr. |
| `themes/questions.py` | `JEV` (40 questions), `free_tags()`, `THEMES`/`ROLES` → `GROUPS` by slug. |
| `themes/data.py` | Theme file format (gzipped CSV + `# {json}` line), download, load into `themes(card, tag, p)`, queries. |
| `themes/tag.py` | Maintainer: `scry maintain tag/export/load`. Imports decide lazily. |

## Themes

- Theme answers are model judgments; README's methodology and known gaps must stay
  accurate when questions, mappings or numbers change.
- Editing a question's wording re-asks only that question (hash per answer in the store,
  `~/.cache/scry/themes/tags.json`). Re-asking costs ~$4.80 per pass over all cards
  plus ~30¢ per question, so batch edits; spending on Jev needs the user's go-ahead.
- Check question changes on `scry maintain tag --sample 500` and with
  `private/score.py` (EDHREC answer key) before a full run.
- `private/` (EDHREC data + fetcher, scorer, research) and `dist/` are gitignored and
  must never be committed: EDHREC's terms forbid redistribution.
- WEAK card-type tags score exactly the threshold (0.50) so they fit but rank last.

## Constraints

- Scryfall: /cards/search, /named, /random, /collection allow ~2 req/s, the rest 10/s.
  Never add retry loops on 429; the cooldown exists because retrying got us
  rate-limited repeatedly. Prefer the local DB for anything card-shaped.
- Freshness = per-set card counts from `/sets` vs the snapshot taken at sync
  (`DB.behind`), checked at most every 24 h. Not the bulk file's date: it changes daily
  for prices alone.
- Bulk-data metadata has served both `download_uri` and `jsonl_download_uri`; handle both.
- Tests are offline: `PYTHONPATH=src:tests python3 -m unittest discover -s tests`.

## Papercuts log (global, all projects)

`~/development/papercuts.md` is a shared log of anything that has slowed down
development — broken tooling, misleading errors, environment quirks.

- **Check it first when tooling fails mysteriously.** The fix may already be recorded.
- **Append to it when you lose time to a papercut mid-session**, one line, newest at the bottom:
  `- YYYY-MM-DD · symptom · fix · project`
- Keep these same instructions in every `CLAUDE.md` under `~/development`.
