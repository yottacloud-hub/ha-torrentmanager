"""Intégration C411 + qBittorrent pour Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.typing import ConfigType

from .api import C411Client, C411Error, QBittorrentClient, QBittorrentError
from .const import (
    CONF_API_KEY,
    CONF_C411_URL,
    CONF_QB_CATEGORY,
    CONF_QB_PASSWORD,
    CONF_QB_SAVE_PATH,
    CONF_QB_TAG,
    CONF_QB_URL,
    CONF_QB_USERNAME,
    CONF_QB_VERIFY_SSL,
    CONF_START_PAUSED,
    DEFAULT_C411_URL,
    DEFAULT_QB_TAG,
    DOMAIN,
    EVENT_DOWNLOAD_ADDED,
    PANEL_COMPONENT,
    PANEL_URL_PATH,
    STATIC_URL,
)
from .coordinator import C411FeedCoordinator, C411RuntimeData, QBittorrentCoordinator
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type C411ConfigEntry = ConfigEntry[C411RuntimeData]

FRONTEND_DIR = Path(__file__).parent / "frontend"
PANEL_FILE = "c411-panel.js"

SERVICE_SEARCH = "search"
SERVICE_DOWNLOAD = "download"
SERVICE_REFRESH = "refresh"

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Optional("query", default=""): cv.string,
        vol.Optional("categories", default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("limit", default=25): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)
DOWNLOAD_SCHEMA = vol.Schema(
    {
        vol.Required("url"): cv.string,
        vol.Optional("category"): cv.string,
        vol.Optional("save_path"): cv.string,
        vol.Optional("paused"): cv.boolean,
        vol.Optional("title"): cv.string,
    }
)


def get_runtime(hass: HomeAssistant) -> C411RuntimeData:
    """Renvoie les données de l'entrée chargée (une seule entrée possible)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise HomeAssistantError("L'intégration C411 n'est pas chargée")


def get_entry(hass: HomeAssistant) -> C411ConfigEntry:
    """Renvoie l'entrée chargée."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise HomeAssistantError("L'intégration C411 n'est pas chargée")


def _safe_filename(title: str | None) -> str:
    base = re.sub(r"[^\w.\-]+", ".", (title or "c411").strip()).strip(".")[:150] or "c411"
    return f"{base}.torrent"


async def async_send_to_qbittorrent(
    hass: HomeAssistant,
    url: str,
    *,
    title: str | None = None,
    category: str | None = None,
    save_path: str | None = None,
    paused: bool | None = None,
) -> dict[str, Any]:
    """Récupère le .torrent sur C411 puis l'envoie à qBittorrent."""
    entry = get_entry(hass)
    rt = entry.runtime_data
    opts = entry.options

    category = category if category is not None else opts.get(CONF_QB_CATEGORY) or None
    save_path = save_path if save_path is not None else opts.get(CONF_QB_SAVE_PATH) or None
    paused = paused if paused is not None else bool(opts.get(CONF_START_PAUSED, False))
    tag = opts.get(CONF_QB_TAG, DEFAULT_QB_TAG)

    try:
        torrent, magnet = await rt.c411.fetch_torrent(url)
    except C411Error as err:
        raise HomeAssistantError(str(err)) from err
    try:
        await rt.qbit.add_torrent(
            torrent=torrent,
            magnet=magnet,
            filename=_safe_filename(title),
            category=category,
            save_path=save_path,
            tags=tag,
            paused=paused,
        )
    except QBittorrentError as err:
        raise HomeAssistantError(str(err)) from err

    event = {"title": title, "url": url, "category": category, "paused": paused}
    hass.bus.async_fire(EVENT_DOWNLOAD_ADDED, event)
    await rt.downloads.async_request_refresh()
    return event


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services et commandes websocket (enregistrés une seule fois)."""

    async def handle_search(call: ServiceCall) -> ServiceResponse:
        rt = get_runtime(hass)
        try:
            results = await rt.c411.search(
                call.data["query"], categories=call.data["categories"] or None,
                limit=call.data["limit"],
            )
        except C411Error as err:
            raise HomeAssistantError(str(err)) from err
        return {"results": [r.as_dict() for r in results]}

    async def handle_download(call: ServiceCall) -> None:
        url = call.data["url"]
        if not (url.startswith("http") or url.startswith("magnet:")):
            raise ServiceValidationError("URL de téléchargement invalide")
        await async_send_to_qbittorrent(
            hass, url,
            title=call.data.get("title"),
            category=call.data.get("category"),
            save_path=call.data.get("save_path"),
            paused=call.data.get("paused"),
        )

    async def handle_refresh(call: ServiceCall) -> None:
        rt = get_runtime(hass)
        await rt.feed.async_request_refresh()
        await rt.downloads.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_SEARCH, handle_search, schema=SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD, handle_download, schema=DOWNLOAD_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, handle_refresh)
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: C411ConfigEntry) -> bool:
    """Mise en place à partir du config entry."""
    data = entry.data
    c411 = C411Client(
        async_get_clientsession(hass),
        data[CONF_API_KEY],
        data.get(CONF_C411_URL, DEFAULT_C411_URL),
    )
    # Session dédiée à qBittorrent : elle garde son propre cookie SID.
    qb_session = async_create_clientsession(
        hass,
        verify_ssl=data.get(CONF_QB_VERIFY_SSL, True),
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    qbit = QBittorrentClient(
        qb_session, data[CONF_QB_URL], data.get(CONF_QB_USERNAME, ""), data.get(CONF_QB_PASSWORD, "")
    )

    feed = C411FeedCoordinator(hass, entry, c411)
    downloads = QBittorrentCoordinator(hass, entry, qbit)
    await downloads.async_config_entry_first_refresh()
    await feed.async_config_entry_first_refresh()

    entry.runtime_data = C411RuntimeData(c411=c411, qbit=qbit, feed=feed, downloads=downloads)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: C411ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: C411ConfigEntry) -> bool:
    """Déchargement."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    return unloaded


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Ajoute le panneau « C411 » dans la barre latérale."""
    if not hass.data.get(f"{DOMAIN}_static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), False)]
        )
        hass.data[f"{DOMAIN}_static"] = True

    version = int(
        await hass.async_add_executor_job(lambda: (FRONTEND_DIR / PANEL_FILE).stat().st_mtime)
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{STATIC_URL}/{PANEL_FILE}?v={version}",
        sidebar_title="C411",
        sidebar_icon="mdi:movie-search",
        require_admin=True,
        config={},
    )
