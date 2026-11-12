"""Catalogue en ligne de Plex (« Discover ») : affiches, notes, titres similaires.

Utilise le même jeton que le serveur Plex : aucune clé supplémentaire.
- Recherche : https://discover.provider.plex.tv/library/search (comme python-plexapi `searchDiscover`)
- Fiches et titres liés : https://metadata.provider.plex.tv/library/metadata/{id}[/related|/similar]
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .matcher import normalize

_LOGGER = logging.getLogger(__name__)

# Adresses modifiables par les tests
DISCOVER = "https://discover.provider.plex.tv"
METADATA = "https://metadata.provider.plex.tv"

TIMEOUT = aiohttp.ClientTimeout(total=15)
TTL_FOUND = 30 * 86400
TTL_MISSING = 7 * 86400
CACHE_MAX = 5000


class PlexMetaError(Exception):
    """Erreur du catalogue Plex."""


class PlexMetaAuthError(PlexMetaError):
    """Jeton refusé par plex.tv."""


def plex_id(guid: str | None) -> str | None:
    """« plex://movie/5d7768…» → « 5d7768… »."""
    if guid and guid.startswith("plex://"):
        return guid.rsplit("/", 1)[-1] or None
    return None


class PlexDiscover:
    """Affiches et recommandations depuis le catalogue Plex."""

    kind = "plex"

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, token: str) -> None:
        self._hass = hass
        self._session = session
        self._token = token
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.plexmeta")
        self._cache: dict[str, Any] = {}
        self._loaded = False
        self._sem = asyncio.Semaphore(6)
        self._related_path: str | None = None  # chemin qui a fonctionné pour les titres liés
        self.image_secret: str | None = None  # renseigné par l'intégration (vue proxy)

    # ------------------------------------------------------------------ HTTP
    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Plex-Token": self._token,
            "X-Plex-Product": "Home Assistant TorrentManager",
            "X-Plex-Client-Identifier": "ha-torrentmanager",
            "X-Plex-Language": "fr",
        }

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            async with self._session.get(url, params=params, headers=self._headers, timeout=TIMEOUT) as resp:
                if resp.status == 401:
                    raise PlexMetaAuthError("Jeton Plex refusé par plex.tv")
                if resp.status in (404, 400):
                    return None
                if resp.status >= 400:
                    raise PlexMetaError(f"Catalogue Plex : HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise PlexMetaError(f"Catalogue Plex injoignable : {err}") from err
        return (data or {}).get("MediaContainer") or {}

    async def image(self, path: str) -> tuple[bytes, str] | None:
        """Image relative du catalogue (rare : la plupart sont des URL complètes)."""
        try:
            async with self._session.get(
                f"{METADATA}{path}", headers={"X-Plex-Token": self._token}, timeout=TIMEOUT
            ) as resp:
                if resp.status >= 400:
                    return None
                return await resp.read(), resp.headers.get("Content-Type", "image/jpeg")
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None

    # ------------------------------------------------------------------ cache
    async def _load(self) -> None:
        if not self._loaded:
            self._cache = await self._store.async_load() or {}
            self._loaded = True

    @callback
    def _save(self) -> None:
        if len(self._cache) > CACHE_MAX:
            for k in list(self._cache)[: len(self._cache) - CACHE_MAX]:
                self._cache.pop(k)
        self._store.async_delay_save(lambda: self._cache, 10)

    def _cached(self, key: str) -> tuple[bool, Any]:
        entry = self._cache.get(key)
        if entry is None:
            return False, None
        ttl = TTL_FOUND if entry.get("found") else TTL_MISSING
        if time.time() - entry.get("at", 0) > ttl:
            return False, None
        return True, entry.get("data")

    def _remember(self, key: str, data: Any) -> None:
        self._cache[key] = {"found": bool(data), "at": time.time(), "data": data}

    # ------------------------------------------------------------------ conversion
    def _poster(self, thumb: str | None) -> str | None:
        if not thumb:
            return None
        if thumb.startswith("https://"):
            return thumb
        if thumb.startswith("/") and self.image_secret:
            return f"/api/c411/plex/meta-image?p={quote(thumb, safe='')}&s={self.image_secret}"
        return None

    def _summary(self, m: dict[str, Any]) -> dict[str, Any] | None:
        kind = m.get("type")
        if kind not in ("movie", "show"):
            return None
        rid = m.get("ratingKey") or plex_id(m.get("guid"))
        if not rid:
            return None
        vote = m.get("audienceRating") or m.get("rating")
        try:
            vote = round(float(vote), 1) if vote else None
        except (TypeError, ValueError):
            vote = None
        ext: dict[str, str] = {}
        for g in m.get("Guid") or []:
            gid = str(g.get("id", "")) if isinstance(g, dict) else ""
            if "://" in gid:
                k, v = gid.split("://", 1)
                ext[k] = v
        return {
            "id": str(rid),
            "tmdbid": ext.get("tmdb"),
            "imdbid": ext.get("imdb"),
            "media": "tv" if kind == "show" else "movie",
            "title": m.get("title"),
            "original_title": m.get("originalTitle") or m.get("title"),
            "year": m.get("year"),
            "poster": self._poster(m.get("thumb")),
            "vote": vote,
            "overview": (m.get("summary") or "")[:400],
        }

    # ------------------------------------------------------------------ recherche
    async def search(self, name: str, year: int | None, media: str | None) -> dict[str, Any] | None:
        """Meilleure correspondance pour un titre (+ année) dans le catalogue."""
        params = {
            "query": name,
            "limit": 10,
            "searchTypes": {"movie": "movies", "tv": "tv"}.get(media or "", "movies,tv"),
            "searchProviders": "discover",
            "includeMetadata": 1,
            "includeGuids": 1,
        }
        data = await self._get(f"{DISCOVER}/library/search", params)
        if not data:
            return None
        results: list[dict[str, Any]] = []
        for block in data.get("SearchResults") or []:
            if block.get("id") in ("external", None) or not results:
                for res in block.get("SearchResult") or []:
                    if isinstance(res.get("Metadata"), dict):
                        results.append(res["Metadata"])
        candidates = [s for s in (self._summary(m) for m in results) if s]
        if media:
            candidates = [c for c in candidates if c["media"] == media] or candidates
        if not candidates:
            return None
        wanted = normalize(name)

        def rank(c: dict[str, Any]) -> tuple[int, int, int]:
            same_title = wanted in (normalize(c["title"] or ""), normalize(c["original_title"] or ""))
            year_ok = year is None or (c["year"] is not None and abs(int(c["year"]) - year) <= 1)
            return (int(same_title and year_ok), int(year_ok), int(same_title))

        best = max(candidates, key=rank)
        if year and best["year"] and abs(int(best["year"]) - year) > 1:
            return None  # année trop différente : mieux vaut pas d'affiche qu'une mauvaise
        return best

    async def lookup(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """{clé: infos} pour une liste d'éléments (même interface que TMDB)."""
        await self._load()
        out: dict[str, Any] = {}
        todo = []
        for item in items:
            media = "tv" if item.get("kind") in ("episode", "pack") or item.get("content_type") in ("series", "anime") else "movie"
            if not item.get("name"):
                continue
            ck = f"s|{media}|{item['name']}|{item.get('year') or ''}"
            hit, data = self._cached(ck)
            if hit:
                out[item["key"]] = data
            else:
                todo.append((ck, item, media))

        async def one(ck: str, item: dict[str, Any], media: str) -> None:
            async with self._sem:
                try:
                    data = await self.search(item["name"], item.get("year"), media)
                except PlexMetaAuthError:
                    raise
                except PlexMetaError as err:
                    _LOGGER.debug("Catalogue Plex indisponible pour %s : %s", item.get("name"), err)
                    return
            self._remember(ck, data)
            out[item["key"]] = data

        if todo:
            await asyncio.gather(*(one(*t) for t in todo))
            self._save()
        return out

    # ------------------------------------------------------------------ recommandations
    async def _related_items(self, rid: str) -> list[dict[str, Any]]:
        """Titres liés à une fiche, en essayant les chemins connus de l'API Plex."""
        paths = [f"/library/metadata/{rid}/related", f"/hubs/metadata/{rid}/related", f"/library/metadata/{rid}/similar"]
        if self._related_path:
            paths.sort(key=lambda p: not p.endswith(self._related_path))
        for path in paths:
            data = await self._get(f"{METADATA}{path}")
            if not data:
                continue
            items: list[dict[str, Any]] = []
            for hub in data.get("Hub") or []:
                items += [m for m in hub.get("Metadata") or [] if isinstance(m, dict)]
            items += [m for m in data.get("Metadata") or [] if isinstance(m, dict)]
            if items:
                self._related_path = path.rsplit("/", 1)[-1]
                return items
        # Dernier recours : les étiquettes « Similar » de la fiche (des titres), à retrouver un par un
        data = await self._get(f"{METADATA}/library/metadata/{rid}")
        meta = ((data or {}).get("Metadata") or [{}])[0]
        titles = [s.get("tag") for s in meta.get("Similar") or [] if s.get("tag")]
        media = "tv" if meta.get("type") == "show" else "movie"
        found = []
        for title in titles[:12]:
            hit = await self.search(title, None, media)
            if hit:
                found.append({"type": "show" if hit["media"] == "tv" else "movie", "ratingKey": hit["id"],
                              "title": hit["title"], "year": hit["year"], "summary": hit["overview"],
                              "audienceRating": hit["vote"], "_poster": hit["poster"]})
        return found

    async def recommendations(self, media: str, rid: str) -> list[dict[str, Any]]:
        """Titres recommandés pour une fiche du catalogue (cache 7 jours)."""
        await self._load()
        ck = f"rec|{rid}"
        hit, data = self._cached(ck)
        if hit and data is not None:
            return data
        out = []
        for m in await self._related_items(rid):
            summary = self._summary(m)
            if summary:
                if not summary["poster"] and m.get("_poster"):
                    summary["poster"] = m["_poster"]
                summary["popularity"] = 0
                out.append(summary)
        # dédoublonnage
        seen: set[str] = set()
        out = [s for s in out if not (s["id"] in seen or seen.add(s["id"]))]
        self._cache[ck] = {"found": True, "at": time.time() - (TTL_FOUND - TTL_MISSING), "data": out}
        self._save()
        return out


_HEX = re.compile(r"^[0-9a-f]{24}$")


def is_plex_id(value: str | None) -> bool:
    """Identifiant du catalogue Plex (24 caractères hexadécimaux)."""
    return bool(value and _HEX.match(value))
