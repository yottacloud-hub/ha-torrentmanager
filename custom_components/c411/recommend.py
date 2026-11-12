"""Recommandations « Pour vous » à partir des téléchargements et de Plex."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .content import content_type
from .releaseinfo import release_info
from .tmdb import TmdbAuthError, TmdbError

_LOGGER = logging.getLogger(__name__)
MAX_SEEDS = 25
CACHE_TTL = 3600


class Recommender:
    """Agrège les recommandations TMDB des contenus déjà téléchargés ou possédés."""

    def __init__(self) -> None:
        self._cache: tuple[float, frozenset, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def build(self, rt: Any, refresh: bool = False) -> dict[str, Any]:
        """Renvoie {configured, items, seeds}."""
        if rt.tmdb is None:
            return {"configured": False, "items": [], "seeds": []}
        async with self._lock:
            seeds, owned = await self._seeds(rt)
            key = frozenset((s["media"], s["id"]) for s in seeds)
            if not refresh and self._cache and self._cache[1] == key and time.time() - self._cache[0] < CACHE_TTL:
                return self._cache[2]

            scores: dict[tuple[str, int], dict[str, Any]] = {}
            sem = asyncio.Semaphore(6)

            async def recs(seed: dict[str, Any]) -> None:
                async with sem:
                    try:
                        items = await rt.tmdb.recommendations(seed["media"], seed["id"])
                    except TmdbAuthError:
                        raise
                    except TmdbError as err:
                        _LOGGER.debug("Recommandations TMDB indisponibles : %s", err)
                        return
                for rank, item in enumerate(items[:20]):
                    k = (item["media"], item["id"])
                    if k in owned:
                        continue
                    entry = scores.setdefault(k, {**item, "score": 0.0, "because": []})
                    entry["score"] += 1.0 + (20 - rank) / 20 + (item.get("vote") or 0) / 20
                    if seed["title"] not in entry["because"]:
                        entry["because"].append(seed["title"])

            await asyncio.gather(*(recs(s) for s in seeds))
            ranked = sorted(scores.values(), key=lambda e: e["score"], reverse=True)[:40]
            for e in ranked:
                e["because"] = e["because"][:3]
                e["score"] = round(e["score"], 2)
            result = {
                "configured": True,
                "items": ranked,
                "seeds": [{"title": s["title"], "media": s["media"], "origin": s["origin"]} for s in seeds],
            }
            self._cache = (time.time(), key, result)
            return result

    async def _seeds(self, rt: Any) -> tuple[list[dict[str, Any]], set[tuple[str, int]]]:
        """Contenus de départ (téléchargements C411 récents, séries Plex suivies) et ce qui est déjà possédé."""
        seeds: list[dict[str, Any]] = []
        plex_seeds: list[dict[str, Any]] = []
        owned: set[tuple[str, int]] = set()

        # Séries Plex : identifiant TMDB direct
        if rt.series is not None:
            for show in (rt.series._shows or {}).values():  # noqa: SLF001
                tmdb = show.get("guids", {}).get("tmdb")
                if tmdb and str(tmdb).isdigit():
                    owned.add(("tv", int(tmdb)))
            followed = [
                s for s in (rt.series.data or {}).get("shows", []) if s.get("follow")
            ]
            for s in followed[:10]:
                show = rt.series._shows.get(s["rating_key"], {})  # noqa: SLF001
                tmdb = show.get("guids", {}).get("tmdb")
                if tmdb and str(tmdb).isdigit():
                    plex_seeds.append({"media": "tv", "id": int(tmdb), "title": s["title"], "origin": "plex"})

        # Téléchargements envoyés depuis C411 (les plus récents d'abord)
        torrents = [t for t in (rt.downloads.data or {}).get("torrents", []) if t.get("is_c411")]
        torrents.sort(key=lambda t: t.get("added_on") or 0, reverse=True)
        items = []
        for t in torrents[:30]:
            info = release_info(t["name"], content_type([]))
            if info["kind"] in ("other",) and not info["year"]:
                continue
            items.append({
                "key": t["hash"], "group": info["group"], "kind": info["kind"], "name": info["name"],
                "year": info["year"], "content_type": "series" if info["kind"] in ("episode", "pack") else "movies",
            })
        if items:
            found = await rt.tmdb.lookup(items)
            for item in items:
                data = found.get(item["key"])
                if data and data.get("id"):
                    owned.add((data["media"], data["id"]))
                    if not any(s["media"] == data["media"] and s["id"] == data["id"] for s in seeds):
                        seeds.append({"media": data["media"], "id": data["id"], "title": data["title"], "origin": "c411"})
        # Les téléchargements passent en premier, puis les séries Plex
        for p in plex_seeds:
            if not any(s["media"] == p["media"] and s["id"] == p["id"] for s in seeds):
                seeds.append(p)
        for s in seeds:
            owned.add((s["media"], s["id"]))
        return seeds[:MAX_SEEDS], owned
