"""Suivi des séries Plex et téléchargement automatique des nouveaux épisodes."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import timedelta
import logging
import secrets
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import C411Client, C411Error
from .const import (
    CONF_PLEX_INTERVAL,
    CONF_PLEX_SECTIONS,
    CONF_SERIES_AUTO,
    CONF_SERIES_EXCLUDE,
    CONF_SERIES_FOLLOW_NEW,
    CONF_SERIES_LANGUAGES,
    CONF_SERIES_MAX_GRABS,
    CONF_SERIES_MIN_SEEDERS,
    CONF_SERIES_NOTIFY,
    CONF_SERIES_PACKS,
    CONF_SERIES_QUALITIES,
    CONF_SERIES_QUALITY,
    DEFAULT_PLEX_INTERVAL,
    DEFAULT_SERIES_EXCLUDE,
    DEFAULT_SERIES_LANGUAGES,
    DEFAULT_SERIES_MAX_GRABS,
    DEFAULT_SERIES_QUALITIES,
    DEFAULT_SERIES_QUALITY,
    DOMAIN,
    EVENT_EPISODE_GRABBED,
    SERIES_CATEGORIES,
)
from .matcher import Rules, code, match_show, parse_release, score, show_keys
from .plex import PlexAuthError, PlexClient, PlexError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
TARGETED_PER_CHECK = 2  # recherches ciblées par cycle (limite C411 : 15 req/min)
POSTER_CACHE_SIZE = 300


def _pack_code(season: int) -> str:
    return f"S{season:02d}"


def _sort_key(avail_key: str) -> tuple[int, int]:
    # "S02E06" / "S02E06-E07" / "S03" → (2, 6) / (2, 6) / (3, 0)
    season = int(avail_key[1:3])
    ep = int(avail_key[4:6]) if len(avail_key) > 3 else 0
    return season, ep


class SeriesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Bibliothèque Plex (séries) + épisodes disponibles sur C411."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, plex: PlexClient, c411: C411Client
    ) -> None:
        minutes = int(entry.options.get(CONF_PLEX_INTERVAL, DEFAULT_PLEX_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_series",
            update_interval=timedelta(minutes=max(10, minutes)),
        )
        self.plex = plex
        self.c411 = c411
        self.poster_secret = secrets.token_urlsafe(16)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.series")
        self._shows: dict[str, dict[str, Any]] = {}
        self._prefs: dict[str, dict[str, bool]] = {}
        self._grabbed: dict[str, dict[str, dict[str, Any]]] = {}
        self._available: dict[str, dict[str, dict[str, Any]]] = {}
        self._rr = 0
        self._lock = asyncio.Lock()
        self._posters: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.last_check: str | None = None
        self.last_check_error: str | None = None
        self.server_name: str | None = None

    # ------------------------------------------------------------ persistance
    async def async_load(self) -> None:
        """Charge les préférences et l'historique."""
        data = await self._store.async_load() or {}
        self._prefs = data.get("prefs", {})
        self._grabbed = data.get("grabbed", {})
        self._available = data.get("available", {})
        self.last_check = data.get("last_check")

    def _snapshot(self) -> dict[str, Any]:
        return {
            "prefs": self._prefs,
            "grabbed": self._grabbed,
            "available": self._available,
            "last_check": self.last_check,
        }

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._snapshot, 2)

    async def async_flush(self) -> None:
        """Écrit immédiatement (au déchargement / rechargement)."""
        await self._store.async_save(self._snapshot())

    # ------------------------------------------------------------ règles
    @property
    def rules(self) -> Rules:
        opts = self.config_entry.options
        exclude = opts.get(CONF_SERIES_EXCLUDE, DEFAULT_SERIES_EXCLUDE) or ""
        return Rules(
            quality=opts.get(CONF_SERIES_QUALITY, DEFAULT_SERIES_QUALITY),
            qualities=list(opts.get(CONF_SERIES_QUALITIES, DEFAULT_SERIES_QUALITIES)),
            languages=list(opts.get(CONF_SERIES_LANGUAGES, DEFAULT_SERIES_LANGUAGES)) or ["vf"],
            min_seeders=int(opts.get(CONF_SERIES_MIN_SEEDERS, 1)),
            exclude=[w.strip() for w in exclude.replace(";", ",").split(",") if w.strip()],
            packs=bool(opts.get(CONF_SERIES_PACKS, True)),
        )

    @property
    def auto_enabled(self) -> bool:
        return bool(self.config_entry.options.get(CONF_SERIES_AUTO, True))

    # ------------------------------------------------------------ bibliothèque Plex
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.server_name is None:
                self.server_name = await self.plex.server_name()
            wanted = set(self.config_entry.options.get(CONF_PLEX_SECTIONS) or [])
            sections = [
                s for s in await self.plex.sections()
                if s["type"] == "show" and (not wanted or s["key"] in wanted)
            ]
            shows: list[dict[str, Any]] = []
            for section in sections:
                shows += await self.plex.shows(section["key"])

            sem = asyncio.Semaphore(4)

            async def load(show: dict[str, Any]) -> None:
                async with sem:
                    show["owned"] = set(await self.plex.episodes(show["rating_key"]))

            await asyncio.gather(*(load(s) for s in shows))
        except PlexAuthError as err:
            raise UpdateFailed(f"Jeton Plex refusé : {err}") from err
        except PlexError as err:
            raise UpdateFailed(str(err)) from err

        follow_new = bool(self.config_entry.options.get(CONF_SERIES_FOLLOW_NEW, True))
        self._shows = {}
        for show in shows:
            key = show["rating_key"]
            owned = show["owned"]
            show["last"] = max(owned) if owned else None
            show["keys"] = show_keys(show["title"], show.get("year")) | (
                show_keys(show["original_title"], show.get("year")) if show["original_title"] else set()
            )
            self._shows[key] = show
            self._prefs.setdefault(key, {"follow": follow_new, "auto": True})
        self._prune()
        self._save()
        return self._payload()

    def _prune(self) -> None:
        """Oublie ce que Plex possède désormais et les séries disparues."""
        for key in list(self._grabbed):
            show = self._shows.get(key)
            if show is None:
                if self._shows:
                    self._grabbed.pop(key, None)
                continue
            owned = show["owned"]
            for c in list(self._grabbed[key]):
                season, ep = _sort_key(c)
                if (ep and (season, ep) in owned) or (not ep and any(s == season for s, _ in owned)):
                    self._grabbed[key].pop(c)
            if not self._grabbed[key]:
                self._grabbed.pop(key)
        for key in list(self._available):
            show = self._shows.get(key)
            if show is None:
                if self._shows:
                    self._available.pop(key, None)
                continue
            for akey, rel in list(self._available[key].items()):
                if not self._is_wanted(show, rel["season"], rel["episodes"]):
                    self._available[key].pop(akey)
            if not self._available[key]:
                self._available.pop(key)

    # ------------------------------------------------------------ recherche C411
    def _grabbed_codes(self, key: str) -> set[str]:
        return set(self._grabbed.get(key, {}))

    def _is_wanted(self, show: dict[str, Any], season: int, episodes: list[int]) -> bool:
        last = show.get("last")
        if not last:
            return False
        grabbed = self._grabbed_codes(show["rating_key"])
        if _pack_code(season) in grabbed:
            return False
        if not episodes:  # pack de saison : seulement pour une saison entièrement absente
            return season > last[0] and not any(c.startswith(_pack_code(season)) for c in grabbed)
        for ep in episodes:
            if (season, ep) <= tuple(last) or (season, ep) in show["owned"] or code(season, ep) in grabbed:
                return False
        return True

    def _ingest(self, releases: list[dict[str, Any]]) -> int:
        """Range les releases intéressantes par série. Renvoie le nombre de nouveautés."""
        shows = list(self._shows.values())
        rules = self.rules
        found = 0
        for rel in releases:
            parsed = parse_release(rel.get("title", ""))
            if parsed is None:
                continue
            show = match_show(parsed, rel, shows)
            if show is None or not self._is_wanted(show, parsed.season, parsed.episodes):
                continue
            points = score(parsed, rel, rules)
            if points is None:
                continue
            akey = (
                _pack_code(parsed.season) if parsed.is_pack
                else parsed.codes[0] + (f"-E{parsed.episodes[-1]:02d}" if len(parsed.episodes) > 1 else "")
            )
            bucket = self._available.setdefault(show["rating_key"], {})
            current = bucket.get(akey)
            if current is None or points > current["score"]:
                if current is None:
                    found += 1
                bucket[akey] = {
                    "key": akey,
                    "season": parsed.season,
                    "episodes": parsed.episodes,
                    "title": rel["title"],
                    "guid": rel["guid"],
                    "download_url": rel["download_url"],
                    "details_url": rel.get("details_url"),
                    "size": rel.get("size", 0),
                    "seeders": rel.get("seeders", 0),
                    "categories": rel.get("categories", []),
                    "quality": parsed.quality,
                    "languages": parsed.languages,
                    "score": points,
                    "found_at": dt_util.utcnow().isoformat(),
                }
        # Un pack de saison remplace les épisodes isolés de la même saison
        for bucket in self._available.values():
            packs = {k for k in bucket if len(k) == 3}
            for k in list(bucket):
                if len(k) > 3 and k[:3] in packs:
                    bucket.pop(k)
        return found

    async def async_check(self, only: str | None = None) -> dict[str, Any]:
        """Cherche les nouveaux épisodes sur C411 puis télécharge si autorisé."""
        async with self._lock:
            if not self._shows:
                await self.async_refresh()
            releases: list[dict[str, Any]] = []
            try:
                if only is None:
                    releases += [
                        r.as_dict() for r in await self.c411.search("", categories=SERIES_CATEGORIES, limit=100)
                    ]
                    targets = self._next_targets()
                else:
                    if only not in self._shows:
                        raise HomeAssistantError("Série inconnue dans Plex")
                    targets = [only]
                for key in targets:
                    show = self._shows[key]
                    query = " ".join(sorted(show["keys"], key=len)[0].split()[:6])
                    releases += [
                        r.as_dict() for r in await self.c411.search(query, categories=SERIES_CATEGORIES, limit=100)
                    ]
                self.last_check_error = None
            except C411Error as err:
                self.last_check_error = str(err)
                _LOGGER.warning("Vérification des séries interrompue : %s", err)
                if only is not None:
                    raise HomeAssistantError(str(err)) from err

            found = self._ingest(releases)
            if found:
                _LOGGER.info("%s nouvel(s) épisode(s) trouvé(s) sur C411", found)
            await self._auto_grab()
            self.last_check = dt_util.utcnow().isoformat()
            self._save()
            payload = self._payload()
            self.async_set_updated_data(payload)
            return payload

    def _next_targets(self) -> list[str]:
        """Quelques séries suivies, à tour de rôle, pour une recherche ciblée."""
        followed = sorted(k for k in self._shows if self._prefs.get(k, {}).get("follow"))
        if not followed:
            return []
        start = self._rr % len(followed)
        self._rr += TARGETED_PER_CHECK
        return [followed[(start + i) % len(followed)] for i in range(min(TARGETED_PER_CHECK, len(followed)))]

    async def _auto_grab(self) -> None:
        if not self.auto_enabled:
            return
        budget = int(self.config_entry.options.get(CONF_SERIES_MAX_GRABS, DEFAULT_SERIES_MAX_GRABS))
        for key in list(self._available):
            prefs = self._prefs.get(key, {})
            if not (prefs.get("follow") and prefs.get("auto")):
                continue
            for akey in sorted(list(self._available.get(key, {})), key=_sort_key):
                if budget <= 0:
                    _LOGGER.info("Limite de téléchargements automatiques atteinte pour ce cycle")
                    return
                try:
                    await self._grab(key, akey, automatic=True)
                    budget -= 1
                except HomeAssistantError as err:
                    _LOGGER.warning("Échec de l'envoi automatique : %s", err)
                    return

    async def _grab(self, key: str, akey: str, *, automatic: bool) -> dict[str, Any]:
        from . import async_send_to_qbittorrent  # noqa: PLC0415 (import circulaire)

        rel = self._available.get(key, {}).get(akey)
        show = self._shows.get(key)
        if rel is None or show is None:
            raise HomeAssistantError("Épisode introuvable (déjà récupéré ?)")
        await async_send_to_qbittorrent(
            self.hass, rel["download_url"], title=rel["title"], categories=rel["categories"]
        )
        codes = [akey] if not rel["episodes"] else [code(rel["season"], e) for e in rel["episodes"]]
        now = dt_util.utcnow().isoformat()
        grabbed = self._grabbed.setdefault(key, {})
        for c in codes:
            grabbed[c] = {"title": rel["title"], "at": now, "auto": automatic}
        self._available[key].pop(akey, None)
        if not self._available[key]:
            self._available.pop(key)
        self._save()

        event = {
            "show": show["title"], "episode": akey, "title": rel["title"],
            "automatic": automatic, "rating_key": key,
        }
        self.hass.bus.async_fire(EVENT_EPISODE_GRABBED, event)
        if self.config_entry.options.get(CONF_SERIES_NOTIFY, True):
            persistent_notification.async_create(
                self.hass,
                f"**{show['title']}** — {akey} envoyé à qBittorrent\n\n`{rel['title']}`",
                title="Nouvel épisode",
                notification_id=f"c411_{key}_{akey}",
            )
        return event

    # ------------------------------------------------------------ actions du panneau
    async def async_grab(self, key: str, akey: str) -> dict[str, Any]:
        """Téléchargement manuel d'un épisode disponible."""
        async with self._lock:
            event = await self._grab(key, akey, automatic=False)
        self.async_set_updated_data(self._payload())
        return event

    async def async_set_prefs(self, key: str, follow: bool | None, auto: bool | None) -> None:
        """Suivre / ne plus suivre, auto ou non."""
        if key not in self._shows:
            raise HomeAssistantError("Série inconnue dans Plex")
        prefs = self._prefs.setdefault(key, {"follow": True, "auto": True})
        if follow is not None:
            prefs["follow"] = follow
        if auto is not None:
            prefs["auto"] = auto
        self._save()
        self.async_set_updated_data(self._payload())

    async def async_forget(self, key: str, akey: str) -> None:
        """Retire un épisode de la liste « récupérés » (pour le re-télécharger)."""
        self._grabbed.get(key, {}).pop(akey, None)
        self._save()
        self.async_set_updated_data(self._payload())

    async def async_poster(self, key: str) -> tuple[bytes, str] | None:
        """Affiche d'une série (mise en cache)."""
        if key in self._posters:
            self._posters.move_to_end(key)
            return self._posters[key]
        show = self._shows.get(key)
        if not show or not show.get("thumb"):
            return None
        try:
            poster = await self.plex.poster(show["thumb"])
        except PlexError:
            return None
        self._posters[key] = poster
        while len(self._posters) > POSTER_CACHE_SIZE:
            self._posters.popitem(last=False)
        return poster

    async def async_refresh_plex_for(self, torrent_name: str) -> None:
        """Après un téléchargement : demande à Plex de scanner la bonne bibliothèque."""
        kind = "show" if parse_release(torrent_name) else None
        try:
            for section in await self.plex.sections():
                if (kind and section["type"] == kind) or (not kind and section["type"] in ("movie", "artist")):
                    await self.plex.refresh_section(section["key"])
        except PlexError as err:
            _LOGGER.warning("Rafraîchissement Plex impossible : %s", err)

    # ------------------------------------------------------------ données
    def _payload(self) -> dict[str, Any]:
        shows = []
        for key, show in self._shows.items():
            prefs = self._prefs.get(key, {"follow": False, "auto": False})
            available = sorted(self._available.get(key, {}).values(), key=lambda r: _sort_key(r["key"]))
            grabbed = sorted(self._grabbed.get(key, {}), key=_sort_key)
            last = show.get("last")
            status = "available" if available else "grabbed" if grabbed else "up_to_date"
            shows.append(
                {
                    "rating_key": key,
                    "title": show["title"],
                    "year": show.get("year"),
                    "has_poster": bool(show.get("thumb")),
                    "follow": prefs.get("follow", False),
                    "auto": prefs.get("auto", False),
                    "last": code(*last) if last else None,
                    "episode_count": len(show.get("owned", ())),
                    "season_count": len({s for s, _ in show.get("owned", ())}),
                    "status": status,
                    "available": [
                        {k: r[k] for k in ("key", "title", "size", "seeders", "quality", "languages", "details_url", "found_at")}
                        for r in available
                    ],
                    "grabbed": [
                        {"code": c, **self._grabbed[key][c]} for c in grabbed
                    ],
                }
            )
        order = {"available": 0, "grabbed": 1, "up_to_date": 2}
        shows.sort(key=lambda s: (not s["follow"], order[s["status"]], s["title"].lower()))
        return {
            "server_name": self.server_name,
            "shows": shows,
            "followed": sum(1 for s in shows if s["follow"]),
            "available_count": sum(len(s["available"]) for s in shows if s["follow"]),
            "last_check": self.last_check,
            "last_check_error": self.last_check_error,
            "auto": self.auto_enabled,
        }
