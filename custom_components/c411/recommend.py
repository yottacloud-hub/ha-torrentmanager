"""Recommandations « Pour vous » à partir des téléchargements et de Plex.

Fournisseur : catalogue Plex (même jeton que le serveur), sinon TMDB si une clé est configurée.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .content import content_type
from .plexmeta import PlexMetaAuthError, PlexMetaError
from .releaseinfo import release_info
from .tmdb import TmdbAuthError, TmdbError

_LOGGER = logging.getLogger(__name__)
MAX_SEEDS = 25
CACHE_TTL = 3600
_ERRORS = (TmdbError, PlexMetaError)
_AUTH_ERRORS = (TmdbAuthError, PlexMetaAuthError)


class Recommender:
    """Agrège les titres recommandés pour les contenus déjà téléchargés ou possédés."""

    def __init__(self) -> None:
        self._cache: tuple[float, Any, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def build(self, rt: Any, refresh: bool = False) -> dict[str, Any]:
        """Renvoie {configured, provider, items, seeds}."""
        providers = [p for p in (rt.plex_meta, rt.tmdb) if p is not None]
        if not providers:
            return {"configured": False, "items": [], "seeds": []}
        async with self._lock:
            result = None
            for provider in providers:
                result = await self._build_with(rt, provider, refresh)
                if result["items"]:
                    break
            return result

    async def _build_with(self, rt: Any, provider: Any, refresh: bool) -> dict[str, Any]:
        seeds, owned = await self._seeds(rt, provider)
        key = (provider.kind, frozenset((s["media"], s["id"]) for s in seeds))
        if not refresh and self._cache and self._cache[1] == key and time.time() - self._cache[0] < CACHE_TTL:
            return self._cache[2]

        scores: dict[tuple[str, str], dict[str, Any]] = {}
        sem = asyncio.Semaphore(6)

        async def recs(seed: dict[str, Any]) -> None:
            async with sem:
                try:
                    items = await provider.recommendations(seed["media"], seed["id"])
                except _AUTH_ERRORS:
                    raise
                except _ERRORS as err:
                    _LOGGER.debug("Recommandations indisponibles pour %s : %s", seed["title"], err)
                    return
            for rank, item in enumerate(items[:20]):
                k = (item["media"], str(item["id"]))
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
            "provider": provider.kind,
            "items": ranked,
            "seeds": [{"title": s["title"], "media": s["media"], "origin": s["origin"]} for s in seeds],
        }
        self._cache = (time.time(), key, result)
        return result

    async def _seeds(self, rt: Any, provider: Any) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
        """Contenus de départ (téléchargements C411 récents, séries Plex suivies) et ce qui est déjà possédé."""
        seeds: list[dict[str, Any]] = []
        plex_seeds: list[dict[str, Any]] = []
        owned: set[tuple[str, str]] = set()

        # Séries de la bibliothèque Plex : identifiants directs, sans recherche
        if rt.series is not None:
            shows = rt.series._shows or {}  # noqa: SLF001
            for show in shows.values():
                for ident in (show.get("plex_id"), show.get("guids", {}).get("tmdb")):
                    if ident:
                        owned.add(("tv", str(ident)))
            for s in [s for s in (rt.series.data or {}).get("shows", []) if s.get("follow")][:10]:
                show = shows.get(s["rating_key"], {})
                ident = show.get("plex_id") if provider.kind == "plex" else show.get("guids", {}).get("tmdb")
                if ident:
                    plex_seeds.append({"media": "tv", "id": str(ident), "title": s["title"], "origin": "plex"})

        # Téléchargements envoyés depuis C411 (les plus récents d'abord)
        torrents = [t for t in (rt.downloads.data or {}).get("torrents", []) if t.get("is_c411")]
        torrents.sort(key=lambda t: t.get("added_on") or 0, reverse=True)
        items = []
        for t in torrents[:30]:
            info = release_info(t["name"], content_type([]))
            if info["kind"] == "other" and not info["year"]:
                continue
            items.append({
                "key": t["hash"], "group": info["group"], "kind": info["kind"], "name": info["name"],
                "year": info["year"], "content_type": "series" if info["kind"] in ("episode", "pack") else "movies",
            })
        if items:
            try:
                found = await provider.lookup(items)
            except _AUTH_ERRORS:
                raise
            except _ERRORS as err:
                _LOGGER.debug("Recherche des téléchargements impossible : %s", err)
                found = {}
            for item in items:
                data = found.get(item["key"])
                if data and data.get("id"):
                    ident = str(data["id"])
                    owned.add((data["media"], ident))
                    if not any(s["media"] == data["media"] and s["id"] == ident for s in seeds):
                        seeds.append({"media": data["media"], "id": ident, "title": data["title"], "origin": "c411"})

        # Les téléchargements passent en premier, puis les séries Plex
        for p in plex_seeds:
            if not any(s["media"] == p["media"] and s["id"] == p["id"] for s in seeds):
                seeds.append(p)
        for s in seeds:
            owned.add((s["media"], s["id"]))
        return seeds[:MAX_SEEDS], owned
