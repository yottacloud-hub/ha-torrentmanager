"""Client minimal pour l'API d'un serveur Plex Media Server."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=30)


class PlexError(Exception):
    """Erreur Plex."""


class PlexAuthError(PlexError):
    """Jeton refusé."""


class PlexClient:
    """Lecture des bibliothèques (séries) d'un serveur Plex."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._token = token

    @property
    def url(self) -> str:
        """Adresse du serveur."""
        return self._url

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Plex-Token": self._token,
            "X-Plex-Product": "Home Assistant C411",
            "X-Plex-Client-Identifier": "ha-c411",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._url}{path}", params=params, headers=self._headers, timeout=TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise PlexAuthError("Jeton Plex refusé")
                if resp.status >= 400:
                    raise PlexError(f"Plex a répondu HTTP {resp.status} ({path})")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise PlexError(f"Impossible de joindre Plex : {err}") from err
        return (data or {}).get("MediaContainer", {})

    async def server_name(self) -> str:
        """Nom du serveur (sert aussi à valider le jeton)."""
        root = await self._get("/")
        await self._get("/library/sections")  # le jeton doit donner accès aux bibliothèques
        return root.get("friendlyName") or "Plex"

    async def sections(self) -> list[dict[str, Any]]:
        """Toutes les bibliothèques : key, title, type (show, movie, artist…)."""
        data = await self._get("/library/sections")
        return [
            {"key": str(d.get("key")), "title": d.get("title"), "type": d.get("type")}
            for d in data.get("Directory", [])
        ]

    async def shows(self, section_key: str) -> list[dict[str, Any]]:
        """Séries d'une bibliothèque, avec leurs identifiants externes."""
        data = await self._get(
            f"/library/sections/{section_key}/all", {"type": 2, "includeGuids": 1}
        )
        shows = []
        for m in data.get("Metadata", []):
            guids: dict[str, str] = {}
            for g in m.get("Guid", []) or []:
                gid = str(g.get("id", ""))
                if "://" in gid:
                    kind, value = gid.split("://", 1)
                    guids[kind] = value
            shows.append(
                {
                    "rating_key": str(m.get("ratingKey")),
                    "title": m.get("title") or "",
                    "original_title": m.get("originalTitle") or "",
                    "year": m.get("year"),
                    "thumb": m.get("thumb"),
                    "guids": guids,
                    "plex_id": str(m.get("guid") or "").rsplit("/", 1)[-1] if str(m.get("guid") or "").startswith("plex://") else None,
                    "section": str(section_key),
                    "episode_count": m.get("leafCount") or 0,
                    "added_at": m.get("addedAt"),
                }
            )
        return shows

    async def episodes(self, rating_key: str) -> list[tuple[int, int]]:
        """(saison, épisode) présents dans Plex pour une série (hors spéciaux)."""
        data = await self._get(f"/library/metadata/{rating_key}/allLeaves")
        result = []
        for ep in data.get("Metadata", []):
            season, number = ep.get("parentIndex"), ep.get("index")
            if isinstance(season, int) and isinstance(number, int) and season > 0:
                result.append((season, number))
        return result

    async def refresh_section(self, section_key: str) -> None:
        """Demande à Plex de rescanner une bibliothèque."""
        try:
            async with self._session.get(
                f"{self._url}/library/sections/{section_key}/refresh",
                headers=self._headers, timeout=TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    raise PlexError(f"Rafraîchissement Plex : HTTP {resp.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PlexError(str(err)) from err

    async def poster(self, thumb: str, width: int = 300, height: int = 450) -> tuple[bytes, str]:
        """Affiche redimensionnée par Plex."""
        params = {
            "width": width, "height": height, "minSize": 1, "upscale": 1, "url": thumb,
        }
        try:
            async with self._session.get(
                f"{self._url}/photo/:/transcode", params=params,
                headers={"X-Plex-Token": self._token}, timeout=TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    raise PlexError(f"Affiche Plex : HTTP {resp.status}")
                return await resp.read(), resp.headers.get("Content-Type", "image/jpeg")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PlexError(str(err)) from err
