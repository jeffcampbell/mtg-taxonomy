"""Name → card: local exact match, unique prefix, close local spelling, then Scryfall
fuzzy (which also finds cards newer than the last sync), then suggestions.

Scryfall's fuzzy matcher can return unrelated cards ("Sol Rng" → Oathsworn Giant), so
its answer is only accepted when the name actually resembles the query.
"""

import difflib

from . import api, db as dbm

AUTO = 0.85  # local spelling similarity accepted without asking
API_MIN = 0.6  # similarity an API fuzzy result needs to be believed


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


class Lookup:
    def __init__(self, db: dbm.DB, online: bool = True):
        self.db = db
        self.online = online
        self._keys = None

    def find(self, name: str) -> tuple[dict | None, str]:
        """Returns (card, note). note is "" for an exact hit, otherwise how it matched or why it didn't."""
        key = dbm.norm(name)
        card = self.db.get(key)
        if card:
            return card, ""
        hits = self.db.prefix(key)
        if len(hits) == 1:
            return self.db.get(dbm.norm(hits[0])), f'"{name}" → {hits[0]}'
        if self._keys is None:
            self._keys = self.db.keys()
        close = difflib.get_close_matches(key, self._keys, n=3, cutoff=0.6)
        if close and similar(key, close[0]) >= AUTO and (len(close) == 1 or similar(key, close[1]) < AUTO):
            card = self.db.get(close[0])
            return card, f'"{name}" → {card["name"]}'
        if self.online:
            try:
                card = dbm.trim(api.get("/cards/named", {"fuzzy": name}))
                if max(similar(key, k) for k in dbm.aliases(card)) >= API_MIN or key in dbm.norm(card["name"]):
                    return card, f'"{name}" → {card["name"]}'
            except api.ApiError as e:
                if e.status in (0, 429):
                    self.online = False  # offline or rate-limited: don't try again for every name
        names = hits or [self.db.get(k)["name"] for k in close]
        return None, f'? "{name}": no match' + (f" (maybe: {' | '.join(names)})" if names else "")
