"""Affiches et infos via TMDB (clé API gratuite, facultative)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from . import const
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=15)
NEGATIVE_TTL = 7 * 86400  # on réessaie au bout d'une semaine si rien n'a été trouvé
CACHE_MAX = 5000


class TmdbError(Exception):
    """Erreur TMDB."""


class TmdbAuthError(TmdbError):
    """Clé refusée."""


class TmdbClient:
    """Petit client TMDB v3 avec cache disque."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession, key: str) -> None:
        self._hass = hass
        self._session = session
        self._key = key.strip()
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.tmdb")
        self._cache: dict[str, Any] = {}
        self._loaded = False
        self._sem = asyncio.Semaphore(8)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        headers = {"Accept": "application/json"}
        if len(self._key) > 40:  # jeton « lecture » v4
            headers["Authorization"] = f"Bearer {self._key}"
        else:
            params["api_key"] = self._key
        try:
            async with self._session.get(
                f"{const.TMDB_API}{path}", params=params, headers=headers, timeout=TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise TmdbAuthError("Clé TMDB refusée")
                if resp.status == 404:
                    return {}
                if resp.status >= 400:
                    raise TmdbError(f"TMDB : HTTP {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TmdbError(str(err)) from err

    async def validate(self) -> None:
        """Vérifie la clé."""
        await self._get("/configuration")

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

    @staticmethod
    def _summary(data: dict[str, Any], media: str) -> dict[str, Any] | None:
        if not data or not data.get("id"):
            return None
        date = data.get("release_date") or data.get("first_air_date") or ""
        return {
            "id": data["id"],
            "media": media,
            "title": data.get("title") or data.get("name"),
            "year": int(date[:4]) if date[:4].isdigit() else None,
            "poster": f"{const.TMDB_IMAGE}{data['poster_path']}" if data.get("poster_path") else None,
            "vote": round(float(data.get("vote_average") or 0), 1) or None,
            "overview": (data.get("overview") or "")[:400],
        }

    async def _resolve(self, item: dict[str, Any]) -> dict[str, Any] | None:
        media = "tv" if item.get("kind") in ("episode", "pack") or item.get("content_type") in ("series", "anime") else "movie"
        lang = {"language": "fr-FR"}
        if item.get("tmdbid"):
            found = self._summary(await self._get(f"/{media}/{item['tmdbid']}", lang), media)
            if found:
                return found
        if item.get("imdbid"):
            imdb = str(item["imdbid"])
            imdb = imdb if imdb.startswith("tt") else f"tt{int(imdb):07d}" if imdb.isdigit() else imdb
            data = await self._get(f"/find/{imdb}", {"external_source": "imdb_id", **lang})
            for key, kind in (("movie_results", "movie"), ("tv_results", "tv")):
                if data.get(key):
                    return self._summary(data[key][0], kind)
        if item.get("name"):
            params = {"query": item["name"], **lang}
            if item.get("year"):
                params["year" if media == "movie" else "first_air_date_year"] = item["year"]
            data = await self._get(f"/search/{media}", params)
            results = data.get("results") or []
            if not results and item.get("year"):
                params.pop("year", None)
                params.pop("first_air_date_year", None)
                results = (await self._get(f"/search/{media}", params)).get("results") or []
            if results:
                return self._summary(results[0], media)
        return None

    async def lookup(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """{clé: infos} pour une liste d'éléments (cache d'abord)."""
        await self._load()
        out: dict[str, Any] = {}
        todo = []
        now = time.time()
        for item in items:
            ck = f"{item.get('tmdbid') or ''}|{item.get('imdbid') or ''}|{item.get('group')}"
            cached = self._cache.get(ck)
            if cached is not None and (cached.get("found") or now - cached.get("at", 0) < NEGATIVE_TTL):
                out[item["key"]] = cached.get("data")
            else:
                todo.append((ck, item))

        async def one(ck: str, item: dict[str, Any]) -> None:
            async with self._sem:
                try:
                    data = await self._resolve(item)
                except TmdbAuthError:
                    raise
                except TmdbError as err:
                    _LOGGER.debug("TMDB indisponible pour %s : %s", item.get("name"), err)
                    return
            self._cache[ck] = {"found": data is not None, "at": now, "data": data}
            out[item["key"]] = data

        if todo:
            await asyncio.gather(*(one(ck, it) for ck, it in todo))
            self._save()
        return out
