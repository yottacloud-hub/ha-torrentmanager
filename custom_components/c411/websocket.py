"""Commandes websocket utilisées par le panneau C411."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import C411Error, QBittorrentError
from .const import (
    CATEGORIES,
    CONTENT_TYPES,
    CONF_QB_CATEGORY,
    CONF_QB_SAVE_PATH,
    CONF_QB_TAG,
    CONF_START_PAUSED,
    DEFAULT_QB_TAG,
    TOP_CATEGORIES,
)

ACTIONS = ["pause", "resume", "delete", "delete_files", "recheck", "reannounce"]


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Enregistre les commandes."""
    for handler in (
        ws_config, ws_latest, ws_search, ws_download, ws_torrents, ws_action,
        ws_series, ws_series_update, ws_series_check, ws_series_grab, ws_series_forget,
    ):
        websocket_api.async_register_command(hass, handler)


def _err(connection: websocket_api.ActiveConnection, msg: dict, err: Exception) -> None:
    connection.send_error(msg["id"], "c411_error", str(err))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "c411/config"})
@websocket_api.async_response
async def ws_config(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Configuration utile au panneau."""
    from . import get_entry  # noqa: PLC0415 (import circulaire)

    try:
        entry = get_entry(hass)
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    rt = entry.runtime_data
    connection.send_result(
        msg["id"],
        {
            "c411_url": rt.c411.base_url,
            "qbittorrent_url": rt.qbit.url,
            "qbittorrent_version": rt.downloads.version,
            "categories": CATEGORIES,
            "top_categories": [[k, v] for k, v in TOP_CATEGORIES.items()],
            "qb_categories": await rt.qbit.categories(),
            "default_category": entry.options.get(CONF_QB_CATEGORY) or "",
            "default_save_path": entry.options.get(CONF_QB_SAVE_PATH) or "",
            "start_paused": bool(entry.options.get(CONF_START_PAUSED, False)),
            "tag": entry.options.get(CONF_QB_TAG, DEFAULT_QB_TAG),
            "folders": [
                {
                    "type": t,
                    "label": label,
                    "path": entry.options.get(f"path_{t}") or entry.options.get(CONF_QB_SAVE_PATH) or "",
                    "category": entry.options.get(f"cat_{t}") or entry.options.get(CONF_QB_CATEGORY) or "",
                }
                for t, label in CONTENT_TYPES.items()
            ],
            "plex": rt.series is not None,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "c411/latest", vol.Optional("refresh", default=False): bool}
)
@websocket_api.async_response
async def ws_latest(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Dernières releases (depuis le cache du coordinateur)."""
    from . import get_runtime  # noqa: PLC0415

    try:
        rt = get_runtime(hass)
        if msg["refresh"]:
            await rt.feed.async_refresh()
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(
        msg["id"],
        {
            "results": rt.feed.data or [],
            "last_update": rt.feed.last_success,
            "error": None if rt.feed.last_update_success else str(rt.feed.last_exception),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "c411/search",
        vol.Optional("query", default=""): str,
        vol.Optional("categories", default=[]): [vol.Coerce(str)],
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=100)),
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def ws_search(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Recherche sur C411."""
    from . import get_runtime  # noqa: PLC0415

    try:
        rt = get_runtime(hass)
        results = await rt.c411.search(
            msg["query"], categories=msg["categories"] or None,
            limit=msg["limit"], offset=msg["offset"],
        )
    except (HomeAssistantError, C411Error) as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], {"results": [r.as_dict() for r in results]})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "c411/download",
        vol.Required("url"): str,
        vol.Optional("title"): str,
        vol.Optional("category"): str,
        vol.Optional("save_path"): str,
        vol.Optional("paused"): bool,
        vol.Optional("categories", default=[]): [vol.Coerce(str)],
        vol.Optional("content_type"): vol.In(list(CONTENT_TYPES)),
    }
)
@websocket_api.async_response
async def ws_download(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Envoie une release vers qBittorrent."""
    from . import async_send_to_qbittorrent  # noqa: PLC0415

    try:
        result = await async_send_to_qbittorrent(
            hass, msg["url"], title=msg.get("title"), categories=msg["categories"],
            ctype=msg.get("content_type"), category=msg.get("category"),
            save_path=msg.get("save_path"), paused=msg.get("paused"),
        )
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "c411/torrents", vol.Optional("live", default=True): bool}
)
@websocket_api.async_response
async def ws_torrents(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """État de qBittorrent."""
    from . import get_runtime  # noqa: PLC0415

    try:
        rt = get_runtime(hass)
        data = await rt.downloads.async_live_refresh() if msg["live"] else rt.downloads.data
    except (HomeAssistantError, UpdateFailed) as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], data)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "c411/torrent_action",
        vol.Required("action"): vol.In(ACTIONS),
        vol.Required("hashes"): [str],
    }
)
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Pause / reprise / suppression."""
    from . import get_runtime  # noqa: PLC0415

    try:
        rt = get_runtime(hass)
        await rt.qbit.action(msg["action"], msg["hashes"])
        data = await rt.downloads.async_live_refresh()
    except (HomeAssistantError, QBittorrentError, UpdateFailed) as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], data)


# --------------------------------------------------------------------- séries
def _series(hass: HomeAssistant):
    from . import get_runtime  # noqa: PLC0415

    return get_runtime(hass).series


def _series_payload(series) -> dict[str, Any]:
    data = dict(series.data or {"shows": []})
    data["configured"] = True
    data["poster_secret"] = series.poster_secret
    data["library_error"] = None if series.last_update_success else str(series.last_exception)
    return data


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "c411/series"})
@websocket_api.async_response
async def ws_series(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Séries Plex et épisodes disponibles."""
    try:
        series = _series(hass)
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    if series is None:
        connection.send_result(msg["id"], {"configured": False, "shows": []})
        return
    connection.send_result(msg["id"], _series_payload(series))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "c411/series_update",
        vol.Required("rating_key"): str,
        vol.Optional("follow"): bool,
        vol.Optional("auto"): bool,
    }
)
@websocket_api.async_response
async def ws_series_update(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Suivre / ne plus suivre une série."""
    try:
        series = _series(hass)
        if series is None:
            raise HomeAssistantError("Plex n'est pas configuré")
        await series.async_set_prefs(msg["rating_key"], msg.get("follow"), msg.get("auto"))
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], _series_payload(series))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "c411/series_check",
        vol.Optional("rating_key"): str,
        vol.Optional("library", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_series_check(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Relit Plex et/ou cherche les nouveaux épisodes (toutes les séries ou une seule)."""
    try:
        series = _series(hass)
        if series is None:
            raise HomeAssistantError("Plex n'est pas configuré")
        if msg["library"]:
            await series.async_refresh()
        await series.async_check(msg.get("rating_key"))
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], _series_payload(series))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "c411/series_grab", vol.Required("rating_key"): str, vol.Required("key"): str}
)
@websocket_api.async_response
async def ws_series_grab(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Télécharge un épisode disponible."""
    try:
        series = _series(hass)
        if series is None:
            raise HomeAssistantError("Plex n'est pas configuré")
        await series.async_grab(msg["rating_key"], msg["key"])
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], _series_payload(series))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "c411/series_forget", vol.Required("rating_key"): str, vol.Required("code"): str}
)
@websocket_api.async_response
async def ws_series_forget(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Oublie un épisode récupéré (il pourra être retéléchargé)."""
    try:
        series = _series(hass)
        if series is None:
            raise HomeAssistantError("Plex n'est pas configuré")
        await series.async_forget(msg["rating_key"], msg["code"])
    except HomeAssistantError as err:
        _err(connection, msg, err)
        return
    connection.send_result(msg["id"], _series_payload(series))
