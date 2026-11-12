"""Tests de bout en bout : vrai Home Assistant + faux C411 / qBittorrent."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from custom_components.c411.api import (
    C411AuthError,
    C411Client,
    C411Error,
    QBittorrentAuthError,
    QBittorrentClient,
)
from custom_components.c411.const import DOMAIN

from .conftest import _start
from .fakes import API_KEY, TORRENT, make_qbit_app


async def _setup(hass: HomeAssistant, servers: dict):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"c411_url": servers["base"], "api_key": "wrong"}
    )
    assert bad["errors"] == {"base": "invalid_api_key"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"c411_url": servers["base"] + "/", "api_key": API_KEY}
    )
    assert result["step_id"] == "qbittorrent"

    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"qb_url": servers["qb_base"], "qb_username": "admin", "qb_password": "nope", "qb_verify_ssl": True},
    )
    assert bad["errors"] == {"base": "invalid_qb_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"qb_url": servers["qb_base"], "qb_username": "admin", "qb_password": "pw", "qb_verify_ssl": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_full_flow(hass: HomeAssistant, servers, hass_ws_client) -> None:
    entry = await _setup(hass, servers)

    # --- Capteurs
    latest = hass.states.get("sensor.c411_derniere_nouveaute") or next(
        s for s in hass.states.async_all("sensor") if "latest" in s.entity_id or "nouveaute" in s.entity_id
    )
    assert latest.state.startswith("Dune.Part.Two")
    assert latest.attributes["count"] == 2
    sensors = {s.entity_id: s.state for s in hass.states.async_all("sensor")}
    print("\nCAPTEURS :", sensors)
    dl = [s for s in hass.states.async_all("sensor") if s.attributes.get("device_class") == "data_rate"]
    assert len(dl) == 2
    assert any(float(s.state) == 2.5 for s in dl)  # 2 500 000 o/s → 2,5 Mo/s

    # --- Panneau
    assert "c411" in hass.data["frontend_panels"]

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "c411/config"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"]["qb_categories"] == ["films", "series"]
    assert msg["result"]["qbittorrent_version"] == "v5.0.1"

    await ws.send_json({"id": 2, "type": "c411/search", "query": "", "categories": ["2000", "5000"]})
    msg = await ws.receive_json()
    assert msg["success"], msg
    res = msg["result"]["results"]
    assert res[0]["seeders"] == 154 and res[0]["freeleech"] is True
    assert res[0]["infohash"] == "a" * 40
    assert res[0]["categories"] == ["2000", "2030"]
    assert servers["c411_calls"][-1]["cat"] == "2000,5000"
    assert res[0]["content_type"] == "movies" and res[1]["content_type"] == "series"

    await ws.send_json({"id": 3, "type": "c411/latest"})
    msg = await ws.receive_json()
    assert msg["success"] and len(msg["result"]["results"]) == 2

    # --- Envoi vers qBittorrent
    events = []
    hass.bus.async_listen("c411_download_added", lambda e: events.append(e))
    await ws.send_json({
        "id": 4, "type": "c411/download", "url": res[1]["download_url"],
        "title": "Shogun S02E03", "category": "series",
    })
    msg = await ws.receive_json()
    assert msg["success"], msg
    added = servers["added"][-1]
    assert added["torrents"]["data"] == TORRENT
    assert added["torrents"]["filename"] == "Shogun.S02E03.torrent"
    assert added["category"] == "series" and added["tags"] == "c411" and added["stopped"] == "false"
    await hass.async_block_till_done()
    assert len(events) == 1
    # l'apikey a bien été ajoutée au lien
    assert servers["c411_calls"][-1]["apikey"] == API_KEY

    # Lien hors C411 refusé
    await ws.send_json({"id": 5, "type": "c411/download", "url": "http://evil.example.com/x.torrent"})
    msg = await ws.receive_json()
    assert not msg["success"] and "C411" in msg["error"]["message"]

    # --- Liste des torrents + actions
    await ws.send_json({"id": 6, "type": "c411/torrents"})
    msg = await ws.receive_json()
    assert msg["success"]
    tors = msg["result"]["torrents"]
    assert tors[0]["hash"] == "a" * 40 and tors[0]["is_c411"] and not tors[1]["is_c411"]
    assert msg["result"]["c411_downloading"] == 1

    await ws.send_json({"id": 7, "type": "c411/torrent_action", "action": "pause", "hashes": ["a" * 40]})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert servers["actions"][-1] == ("stop", {"hashes": "a" * 40})

    await ws.send_json({"id": 8, "type": "c411/torrent_action", "action": "delete_files", "hashes": ["dddd"]})
    msg = await ws.receive_json()
    assert servers["actions"][-1] == ("delete", {"hashes": "dddd", "deleteFiles": "true"})

    # --- Événement de fin de téléchargement
    done = []
    hass.bus.async_listen("c411_download_completed", lambda e: done.append(e))
    servers["torrents"][0]["progress"] = 1
    servers["torrents"][0]["state"] = "uploading"
    await entry.runtime_data.downloads.async_refresh()
    await hass.async_block_till_done()
    assert len(done) == 1 and done[0].data["from_c411"] is True

    # --- Service de recherche (avec réponse)
    resp = await hass.services.async_call(
        DOMAIN, "search", {"query": "dune", "limit": 5}, blocking=True, return_response=True
    )
    assert len(resp["results"]) == 1

    await hass.services.async_call(DOMAIN, "download", {"url": res[0]["download_url"]}, blocking=True)
    assert len(servers["added"]) == 2 and "category" not in servers["added"][-1]

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "download", {"url": "https://other.site/a"}, blocking=True)

    # --- Options puis rechargement
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "general"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "general"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"feed_categories": ["2000"], "feed_limit": 20, "feed_interval": 15, "qb_category": "films",
         "qb_tag": "c411", "start_paused": True, "qb_interval": 5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert servers["c411_calls"][-1]["cat"] == "2000" and servers["c411_calls"][-1]["limit"] == "20"
    assert "c411" in hass.data["frontend_panels"]

    await hass.services.async_call(DOMAIN, "download", {"url": res[0]["download_url"]}, blocking=True)
    assert servers["added"][-1]["category"] == "films" and servers["added"][-1]["stopped"] == "true"

    # --- Déchargement
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "c411" not in hass.data["frontend_panels"]


async def test_auth_failure_triggers_reauth(hass: HomeAssistant, servers) -> None:
    entry = await _setup(hass, servers)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "api_key": "revoked"})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_clients_directly(hass: HomeAssistant, servers) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession, async_create_clientsession
    import aiohttp

    session = async_get_clientsession(hass)
    c = C411Client(session, API_KEY, servers["base"])
    data, magnet = await c.fetch_torrent(f"{servers['base']}/api/torznab?t=get&id=redirect")
    assert data == TORRENT and magnet is None
    data, magnet = await c.fetch_torrent(f"{servers['base']}/api/torznab?t=get&id=magnet")
    assert data is None and magnet.startswith("magnet:")
    with pytest.raises(C411AuthError):
        await C411Client(session, "bad", servers["base"]).search("x")
    with pytest.raises(C411Error):
        await c.fetch_torrent("http://example.org/api/torznab?t=get&id=1")

    # qBittorrent v4 : repli pause/resume
    state = {"qb_base": None}
    runner, base = await _start(make_qbit_app(state, v5=False))
    state["qb_base"] = base
    try:
        qb = QBittorrentClient(
            async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True)), base, "admin", "pw"
        )
        assert await qb.version() == "v4.6.7"
        await qb.action("pause", ["x"])
        await qb.action("resume", ["x"])
        assert [a[0] for a in state["actions"]] == ["pause", "resume"]
        await qb.add_torrent(magnet="magnet:?xt=urn:btih:cccc", tags="c411")
        assert state["added"][-1]["urls"].startswith("magnet:")

        bad = QBittorrentClient(
            async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar(unsafe=True)), base, "admin", "x"
        )
        with pytest.raises(QBittorrentAuthError):
            await bad.version()
    finally:
        await runner.cleanup()


async def test_torrent_errors(hass: HomeAssistant, servers, hass_ws_client) -> None:
    """Fichier refusé par C411, fichier sans torrent, fichier refusé par qBittorrent."""
    await _setup(hass, servers)
    ws = await hass_ws_client(hass)
    base = servers["base"]

    # C411 refuse : message clair, rien n'est envoyé
    n = len(servers["added"])
    await ws.send_json({"id": 1, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=failure"})
    msg = await ws.receive_json()
    assert not msg["success"] and "Torrent introuvable" in msg["error"]["message"]
    assert len(servers["added"]) == n

    # Réponse sans torrent : on confie le lien à qBittorrent
    await ws.send_json({"id": 2, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=noinfo"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert servers["added"][-1]["urls"] == f"{base}/api/torznab?t=get&id=noinfo&apikey={API_KEY}"

    # qBittorrent refuse le fichier (415) : nouvel essai avec le lien
    servers["qb_reject_files"] = True
    await ws.send_json({"id": 3, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=1001",
                        "categories": ["2000"]})
    msg = await ws.receive_json()
    assert msg["success"], msg
    added = servers["added"][-1]
    assert "torrents" not in added and added["urls"].endswith(f"id=1001&apikey={API_KEY}")
    assert added["tags"] == "c411"
