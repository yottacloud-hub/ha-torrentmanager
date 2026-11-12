"""Coordinateurs de mise à jour (flux C411 et état qBittorrent)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    C411AuthError,
    C411Client,
    C411Error,
    QBittorrentAuthError,
    QBittorrentClient,
    QBittorrentError,
)
from .content import filter_adult
from .const import (
    CONF_HIDE_ADULT,
    CONF_FEED_CATEGORIES,
    CONF_FEED_INTERVAL,
    CONF_FEED_LIMIT,
    CONF_QB_INTERVAL,
    CONF_QB_TAG,
    DEFAULT_FEED_INTERVAL,
    DEFAULT_FEED_LIMIT,
    DEFAULT_QB_INTERVAL,
    DEFAULT_QB_TAG,
    DOMAIN,
    EVENT_DOWNLOAD_COMPLETED,
    EVENT_NEW_RELEASES,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class C411RuntimeData:
    """Objets partagés par l'intégration."""

    c411: C411Client
    qbit: QBittorrentClient
    feed: C411FeedCoordinator
    downloads: QBittorrentCoordinator
    series: Any = None  # SeriesCoordinator quand Plex est configuré
    tmdb: Any = None  # TmdbClient quand une clé TMDB est configurée


class C411FeedCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Récupère régulièrement les dernières releases C411."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: C411Client) -> None:
        minutes = int(entry.options.get(CONF_FEED_INTERVAL, DEFAULT_FEED_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_feed",
            update_interval=timedelta(minutes=max(5, minutes)),
        )
        self.client = client
        self._seen: set[str] | None = None
        self.last_success: str | None = None

    async def _async_update_data(self) -> list[dict[str, Any]]:
        opts = self.config_entry.options
        try:
            releases = await self.client.search(
                "",
                categories=opts.get(CONF_FEED_CATEGORIES) or None,
                limit=int(opts.get(CONF_FEED_LIMIT, DEFAULT_FEED_LIMIT)),
            )
        except C411AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except C411Error as err:
            raise UpdateFailed(str(err)) from err

        data = filter_adult([r.as_dict() for r in releases], opts.get(CONF_HIDE_ADULT, True))
        guids = {r["guid"] for r in data}
        if self._seen is not None:
            new = [r for r in data if r["guid"] not in self._seen]
            if new:
                self.hass.bus.async_fire(
                    EVENT_NEW_RELEASES,
                    {
                        "count": len(new),
                        "releases": [
                            {"title": r["title"], "size": r["size"],
                             "categories": r["categories"], "details_url": r["details_url"]}
                            for r in new[:20]
                        ],
                    },
                )
            self._seen |= guids
        else:
            self._seen = set(guids)
        self.last_success = dt_util.utcnow().isoformat()
        return data


class QBittorrentCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Suit l'état de qBittorrent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: QBittorrentClient) -> None:
        seconds = int(entry.options.get(CONF_QB_INTERVAL, DEFAULT_QB_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_qbittorrent",
            update_interval=timedelta(seconds=max(3, seconds)),
        )
        self.client = client
        self.tag = entry.options.get(CONF_QB_TAG, DEFAULT_QB_TAG)
        self._progress: dict[str, float] | None = None
        self.version: str | None = None

    async def fetch(self) -> dict[str, Any]:
        """Lecture immédiate (utilisée aussi par le panneau)."""
        try:
            if self.version is None:
                self.version = await self.client.version()
            transfer = await self.client.transfer_info()
            torrents = await self.client.torrents()
        except QBittorrentAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except QBittorrentError as err:
            raise UpdateFailed(str(err)) from err

        for tor in torrents:
            tor["is_c411"] = self.tag in tor["tags"]
        self._detect_completed(torrents)

        downloading_states = {"downloading", "forcedDL", "metaDL", "forcedMetaDL", "stalledDL", "queuedDL", "checkingDL", "allocating"}
        return {
            "version": self.version,
            "dl_speed": transfer.get("dl_info_speed", 0),
            "up_speed": transfer.get("up_info_speed", 0),
            "connection_status": transfer.get("connection_status"),
            "torrents": torrents,
            "count": len(torrents),
            "downloading": sum(1 for t in torrents if t["state"] in downloading_states),
            "c411_downloading": sum(
                1 for t in torrents if t["is_c411"] and t["state"] in downloading_states
            ),
            "c411_count": sum(1 for t in torrents if t["is_c411"]),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        return await self.fetch()

    async def async_live_refresh(self) -> dict[str, Any]:
        """Rafraîchit immédiatement et pousse les données aux entités."""
        data = await self.fetch()
        self.async_set_updated_data(data)
        return data

    def _detect_completed(self, torrents: list[dict[str, Any]]) -> None:
        current = {t["hash"]: float(t["progress"] or 0) for t in torrents}
        if self._progress is not None:
            for tor in torrents:
                before = self._progress.get(tor["hash"])
                if before is not None and before < 1 and current[tor["hash"]] >= 1:
                    self.hass.bus.async_fire(
                        EVENT_DOWNLOAD_COMPLETED,
                        {
                            "name": tor["name"],
                            "hash": tor["hash"],
                            "size": tor["size"],
                            "category": tor["category"],
                            "save_path": tor["save_path"],
                            "from_c411": tor["is_c411"],
                        },
                    )
        self._progress = current
