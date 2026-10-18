# scry

Magic: The Gathering card data for AI agents: Scryfall card lookups in as few tokens
as possible, plus deck themes for every card.

(This repository is **mtg-taxonomy**; the command-line tool it installs is `scry`.)

```console
$ scry card -f themes "Blood Artist" "fell the profane" "Sol Rng"
Blood Artist · 1B · Creature — Vampire · 0/1
themes:lifegain,aristocrats,sacrifice,group-slug,lifedrain
Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.

Fell the Profane · 2BB · Instant
roles:removal
Destroy target creature or planeswalker.
// Fell Mire · Land
As this land enters, you may pay 3 life. If you don't, it enters tapped.
{T}: Add {B}.

# "Sol Rng" → Sol Ring
Sol Ring · 1 · Artifact
themes:artifacts,ramp,big-mana,historic
{T}: Add {C}{C}.

$ scry themes aristocrats --ci wb -n 3
# Aristocrats: 2,450 cards in WB, top 3 by score then popularity
0.99 Lazotep Quarry · Land — Desert
0.99 Fain, the Broker · 2B · Legendary Creature — Human Warlock · 3/3
0.98 Gray Merchant of Asphodel · 3BB · Creature — Zombie · 2/4

$ scry deck --themes https://archidekt.com/decks/10420996
# [Bracket 2] Amalia/Lurrus · 100 cards
# themes: lifegain 30 · lifedrain 28 · historic 18 · aristocrats 17 · tokens 14 · …
# roles: removal 7 · board-wipe 5 · protection 5 · tutor 3 · counterspell 0 · bounce 0
```

Pure Python standard library, 3.11+. No API key needed to use it.

## Install

```sh
pip install git+https://github.com/jeffcampbell/mtg-taxonomy.git
scry sync        # ~25 MB of card data + ~1.3 MB of theme data into ~/.cache/scry
```

Or run from a checkout: `bin/scry …`. The first command syncs automatically. Data
lives in `~/.cache/scry/cards.db` (or `$SCRY_CACHE_DIR`), so lookups are local and
take milliseconds.

## Commands

| | |
|---|---|
| `scry card NAME…` | Cards by name; or names on stdin, one per line (deck-list lines like `1x Sol Ring (CMR) 263` work) |
| `scry deck SOURCE` | Every card in an Archidekt URL, a deck-list file, or `-` (stdin), grouped commander / companion / main. `--themes` prints only a theme summary |
| `scry themes [THEME…]` | No argument: every theme and role with card counts. With themes: the top cards fitting all of them, best first; `--ci wb` limits color identity, `-n` the count, `-t` adds rules text |
| `scry search QUERY` | [Scryfall search syntax](https://scryfall.com/docs/syntax); one line per card, `-t` adds rules text, `-n 0` counts only |
| `scry rulings NAME…` | Official rulings; `-g REGEX` keeps only matching ones, `-n` caps the count |
| `scry sync` | Re-download card and theme data (`--check`, `--if-needed`: see below) |

Shared flags: `-s` header line only · `-f ci,price,rank,gc,kw,legal,set,rarity,themes`
(or `all`) adds one line of extra fields · `--raw` keeps reminder text and the card's
own name · `--offline` never calls the API.

## Output format

- `Name · cost · type · P/T`, then rules text. Costs drop braces for plain symbols
  (`2WW` = `{2}{W}{W}`) and keep them for hybrid/Phyrexian (`{W/B}`).
- Reminder text is dropped and the card's own name is `~` (`--raw` keeps both).
- `// ` starts another face of a multi-face card.
- `# ` lines are notes (e.g. a corrected spelling); `? ` lines are cards not found,
  with suggestions, and make the exit status 1.
- `themes:` and `roles:` (with `-f themes`) list theme slugs; `scry themes` lists them all.
  Scores in `scry themes` output are the model's P(yes), 0.50–1.00 (see below).

## Name matching

Exact (ignoring case, accents and punctuation; either face of a multi-face card) →
unique prefix (`lurrus`) → a close local spelling (`blod artst`) → Scryfall's fuzzy
match, which also finds cards printed after your last sync. Scryfall's fuzzy matcher
sometimes returns unrelated cards (`Sol Rng` → Oathsworn Giant), so scry only
accepts its answer when the name resembles the query.

## Keeping it current

Scryfall regenerates its bulk file daily for prices, so the file's date can't tell
you whether there are new cards. Per-set card counts can: `sync` saves a snapshot of
them, and at most once a day any online command fetches `/sets` (one ~600 KB request)
and compares. When sets have grown you get one stderr line on every run until you sync:

    scry: Scryfall has cards newer than your data (mdd +3, mdc (new)); run `scry sync` (names still resolve online meanwhile)

Until then, card names missing locally still resolve through Scryfall's API, and
`search` and `rulings` always use the API. A 14-day age warning covers oracle errata
and prices, which set counts don't reflect.

| | |
|---|---|
| `scry sync --check` | Print `behind: …` and exit 1, or `up to date` and exit 0 |
| `scry sync --if-needed` | Sync only when behind or older than 14 days; for cron, e.g. `0 6 * * * scry sync --if-needed` |

Theme data is published separately (see [Updating the theme data](#updating-the-theme-data)).
Cards newer than it still get the tags that come from card data, but not the model's
answers, until the next theme release.

## How small is it?

The 84 unique cards in an example Commander deck, in characters (about 4 per token):

| | chars | per card |
|---|---:|---:|
| Scryfall JSON | 437,831 | 5,212 |
| Scryfall `format=text` | 17,606 | 210 |
| `scry card` | 15,092 | 180 |
| `scry card -s` | 4,145 | 49 |

Against Scryfall's own text format the savings per card are small (reminder text and
self-names). The bigger wins for an agent: a whole deck or list comes back from one
command instead of a call per card, `-s` lets it skim before reading, misspellings
resolve without a retry, rulings can be filtered, and theme questions ("what are this
deck's themes?", "best aristocrats cards in Orzhov?") are answered locally.

## Using it from a coding agent

> For Magic card information, use `scry` (on PATH). `scry card A B C` for cards by
> name, `scry deck <archidekt-url|file|->` for a whole deck (`--themes` for a theme
> summary), `scry themes <theme> --ci <colors>` for cards that fit a theme,
> `scry search '<scryfall query>'` to find cards, `scry rulings NAME -g WORD` for
> rulings. Add `-s` to skim headers only. `~` in rules text means the card itself.
> Themes are a model's judgment, not official data.

---

# Themes

Every card is tagged with the deck themes it fits — 43 themes named after EDHREC's
theme vocabulary (Tokens, Aristocrats, Spellslinger, …) and 6 staple roles (removal,
board wipe, protection, tutor, counterspell, bounce).

**These are judgments made by a language model reading each card's rules text, not
official or human-curated data.** They agree with EDHREC's synergy data for a median
80% of each theme's signature cards (details and limits below). Use them to search,
summarize and shortlist, not as ground truth.

## Methodology

**1. Card text.** Each card is rendered in scry's compact format (name, cost, type,
stats, rules text without reminder text) — the same text `scry card` prints.

**2. Forty yes/no questions.** Each card's text goes to
[Jev](https://jevtypesafeai.com/jev/api), a decision model from TypeSafe that only
answers typed questions and returns probabilities, via
[`decide`](https://github.com/jeffcampbell/Decide). One request per card asks 40
questions like *"Does this card reward you for gaining life (triggers or bonuses when
you gain life)?"*. The full wording is in
[`src/scry/themes/questions.py`](src/scry/themes/questions.py). An answer counts as
yes at P(yes) ≥ 0.5.

**3. Twenty-three free tags.** Things the card data states outright are read directly
instead of asked: card types (Equipment, Aura, legendary, …), keywords (flying,
infect, storm, landfall, …) and exact phrases ("counter target … spell", "mill",
"additional combat", returning a permanent to its owner's hand, …).

**4. Themes from tags.** Each theme is a set of tags; a card fits if any applies.
Aristocrats = sacrifice outlet *or* death trigger *or* drain. Themes deliberately
include both enablers and payoffs, because that's how decks are built: a Tokens deck
wants cards that make tokens *and* cards that reward having them.

**5. Scores.** A card's score for a theme is its highest P(yes) among the theme's
tags (free tags count as 1.00). Card-type tags that make a card fit a theme without
saying it cares — a cheap instant fits Spellslinger, any artifact fits Artifacts —
score exactly 0.50: they count as fitting but rank below cards the model confirmed.
`scry themes` sorts by score (rounded to 0.01), then by EDHREC popularity rank.

**The run.** 33,154 cards (every Oracle card except tokens, art cards and
Planechase/Archenemy/Vanguard cards), October 18, 2026, model `jev-latest`: about 44
million input tokens, $18.34, 9 minutes, 0 errors.

## How it was tested

**Against EDHREC.** For 43 themes we took EDHREC's 15 highest-synergy cards (synergy
≥ 0.10, excluding commander lists, "top cards" and plain lands) — 521 cards — and
measured *recall*: the share of a theme's signature cards that our tags put in that
theme. We also measured a *base rate*: how often the same theme fires on the other
themes' cards.

| | |
|---|---|
| Median recall | 80% (32 of 43 themes at 70% or more) |
| Median base rate | 8% |
| 85–100% | Tokens, Aristocrats, Sacrifice, Lifegain, Auras, Enchantress, Equipment, Artifacts, Lands Matter, Legends, Historic, Treasure, X Spells, Infect, Wheels, Spellslinger, Blink |
| 70–80% | +1/+1 Counters, Graveyard, Reanimator, Self-Mill, Clones, Mill, Flying, Storm, Card Draw, ETB, Landfall, Group Slug, Big Mana, -1/-1 Counters, Theft |
| below 70% | Voltron, Group Hug (67%), Burn, Stax, Extra Combats, Lifedrain (60%), Discard, Forced Combat, Extra Turns (53%), Ramp (50%), Pillow Fort (40%) |

**Against the rules text.** On a random 500 cards (all colors, 62–85 cards each), we
compared tags with exact-phrase searches of the rules text — e.g. every card saying
"counter target spell" should be tagged counterspell. This caught a case-sensitivity
bug in the free tags (counterspell 0/8 → 8/8) and four badly worded questions: board
wipes that shrink or damage rather than destroy (1/5 → 4/5), ramp that searches for
lands (3/6 → 6/6), stax that tagged plain counterspells, and pillow fort that tagged
anything with defender. All were fixed before the full run.

**Iteration.** The question set went through three rounds. A 64-question draft showed
that vague strategic questions ("group hug", "alt win") produce noise; the first
40-question draft reached 70% recall on 23 themes; adding enablers (discard payoffs,
draw payoffs, creatures with enter-the-battlefield value, cheap spells, rituals) took
Wheels, Storm, Card Draw, ETB and Spellslinger from roughly 40% to 80–93%.

## Why this method

**Read the card, don't recognize it.** Given only names, Jev agreed with its own
text-based answers on 54 of 84 cards; the rest were guesses from the words in the name
("Guide of Souls" → reanimation). Every answer here comes from the rules text, so it
also works for cards the model has never heard of.

**Yes/no per theme, not "pick a category".** Cards belong to several themes at once
(Blood Artist is Aristocrats *and* Lifegain), which a single pick can't express. Pick-
one questions also proved order-sensitive: rotating the option list changed the top
pick on 6 of 84 cards — all close calls. Yes/no questions showed no such effect:
reversing or shuffling 13 questions, or asking 64 at once instead of 13, changed
answers no more than repeating the identical request (mean change 0.004 or less in every case).

**A small decision model, not a chat model.** Jev returns calibrated probabilities
instead of prose, costs $0.42 per million input tokens (the whole card pool for $18),
and answers are cached by exact input, so results are reproducible and re-runs are
free. Probabilities make thresholds and rankings possible; prose would need parsing.

**Free tags for anything lexical.** Keywords and card types are exact and cost
nothing, so the model is only asked what requires reading comprehension.

**EDHREC's vocabulary, our own judgments.** Naming themes the way players already do
makes results comparable and familiar. Copying EDHREC's assignments instead would
measure something different: EDHREC's synergy is deck co-occurrence, which mixes what
a card *does* with which colors and archetypes it travels with (Signets show up as
"Burn" cards). We use EDHREC only to check our work, and don't redistribute its data.

**Recall understates accuracy on noisy themes.** Many "misses" are cards EDHREC lists
for reasons other than the theme: cEDH staples (Force of Will, Vampiric Tutor) under
Extra Turns and Stax, mana rocks under Burn and Lifedrain, no-maximum-hand-size cards
under Card Draw. Checking misses by hand repeatedly found the model was right
(Stromkirk Captain gains no life; Horde of Notions has no enter-the-battlefield
ability).

## Known gaps

- **No human-labeled ground truth.** Accuracy is measured against EDHREC's synergy
  lists (noisy, biased toward popular Commander cards) and spot checks, not a
  hand-labeled set.
- **Ramp (50%)** is measured badly: ramp is in every deck, so its top-synergy cards
  are lands-matter commanders. Mana from lands entering is covered only since the
  last round of fixes.
- **Pillow Fort (40%) and Forced Combat (53%)** have thin coverage; Forced Combat
  relies on the goad keyword plus nothing else.
- **Stax** still tags some single-target auras (Sleeping Potion, Petrify) and misses
  some real stax (Collector Ouphe, 0.27).
- **Theft** misses some cards that let you cast opponents' cards (Gonti, Night
  Minister, 0.43).
- **Blink and ETB are identical** (same tags); **Historic, Legends, Artifacts, Storm
  and Spellslinger are broad** because card type alone makes a card fit (scored 0.50,
  ranked last).
- **Base rates of 8% (up to 37% for Historic)** are partly real overlap and partly
  over-tagging; a theme's card count is "cards that fit", not "cards built for it".
- **Not covered:** archetypes that describe whole decks (Combo, Aggro, Control,
  Midrange, Good Stuff), creature-type themes (Dragons, Elves, …), and EDHREC themes
  outside the 43 mapped.
- **27 names belong to more than one distinct card** (e.g. a new layout of Swords to
  Plowshares); they share one set of answers.
- **Cards newer than the theme data** get free tags only until the next release.
- **Model drift.** `jev-latest` can change; a re-tag with a newer model may shift
  scores. Each release records its date, model and a hash of every question.
- **The 0.5 threshold** is a convention, not tuned per question.

## Theme data format

`scry-themes.csv.gz`, published as a GitHub Release asset and downloaded by
`scry sync`:

```
# {"format":1,"date":"2026-10-18","model":"jev-latest","threshold":0.5,"cards":33154,"questions":{"creature_tokens":"a99c0a6e",…}}
name,creature_tokens,token_payoff,…
Blood Artist,0.03,0.03,0.02,0.03,0.08,…
```

One row per card with each question's P(yes) to two decimals; `questions` maps each
column to a hash of the exact wording it answers. Free tags aren't shipped — they're
computed from card data at load. `scry maintain load FILE` loads a file by hand.

## Updating the theme data

Maintainers only; needs [`decide`](https://github.com/jeffcampbell/Decide) and a
TypeSafe API key:

```sh
scry sync                                  # pick up new cards
scry maintain tag --all --dry-run          # what would be asked, estimated cost
scry maintain tag --all                    # only cards (or questions) not yet answered
scry maintain export scry-themes.csv.gz    # then attach it to a new GitHub release
```

Answers accumulate in `~/.cache/scry/themes/tags.json`; each records a hash of its
question's wording, so editing a question in `questions.py` re-asks only that
question. New cards cost about $1 a year; re-asking one question over every card about
$4.80 (mostly fixed per-request overhead), so batch question changes.

---

## Scryfall etiquette

scry sends the `User-Agent`/`Accept` headers Scryfall requires and spaces requests
(500 ms for search/named/collection, 100 ms otherwise). After a 429, every scry
process stays off the API for two minutes; repeated violations get clients blocked.
Card lookups use the local database and don't touch the API at all.

Moxfield blocks scripted access: export the deck as text and use `scry deck - < list.txt`.

## Development

```sh
PYTHONPATH=src:tests python3 -m unittest discover -s tests   # offline
```

## Credits

- **[Scryfall](https://scryfall.com)** — all card data (Oracle text, types, keywords,
  prices, EDHREC ranks, set information) comes from Scryfall's API and bulk data.
  scry is free to use and doesn't redistribute card images.
- **[EDHREC](https://edhrec.com)** — the theme names follow EDHREC's theme
  vocabulary, and EDHREC's public synergy data was the yardstick for testing the
  tags. EDHREC's terms don't allow redistributing its data, so neither that data nor
  the scripts that read it are included here.
- **[TypeSafe Jev](https://jevtypesafeai.com/jev/api)** — the decision model that
  answered the theme questions, called through
  [decide](https://github.com/jeffcampbell/Decide).

scry is unofficial Fan Content permitted under the
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not
approved/endorsed by Wizards. Portions of the materials used are property of Wizards
of the Coast. ©Wizards of the Coast LLC. scry is not affiliated with Scryfall, EDHREC
or TypeSafe.

## License

Code: MIT ([LICENSE](LICENSE)). Theme data (`scry-themes.csv.gz`): CC BY 4.0
([DATA_LICENSE](DATA_LICENSE)). Card names and rules text belong to Wizards of the
Coast.
