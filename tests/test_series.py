"""Plex, suivi des séries et dossiers par type."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.c411.const import DOMAIN

from .fakes import ITEMS, PLEX_TOKEN, PNG
from .test_integration import _setup


def _item(i, title, cats=("5000",), seeders=30, **kw):
    return {"id": str(i), "title": title, "size": 1_500_000_000, "cats": list(cats), "seeders": seeders,
            "peers": 2, "grabs": 10, "infohash": f"{i:040d}", **kw}


async def _options(hass, entry, step, data):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})
    assert result["type"] is FlowResultType.FORM, result
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return result


async def test_series_tracking(hass: HomeAssistant, servers, hass_ws_client, hass_client_no_auth) -> None:
    servers["items"] = ITEMS + [
        _item(2001, "Shogun.2024.S02E03.MULTi.1080p.WEB.H264-AAA", tmdbid="126308"),
        _item(2002, "Shogun.2024.S02E03.VOSTFR.1080p.WEB.H264-BBB", seeders=300),
        _item(2003, "Shogun.2024.S02E04.MULTi.2160p.WEB.H265-CCC"),
        _item(2004, "Shogun.2024.S02E02.MULTi.1080p.WEB.H264-DDD"),
        _item(2005, "Severance.S03.MULTi.1080p.ATVP.WEB-DL.DDP5.1-EEE"),
        _item(2006, "Severance.S03E01.MULTi.1080p.ATVP.WEB-DL-FFF"),
        _item(2007, "Le.Bureau.des.Legendes.S05E10.FRENCH.1080p.WEB", seeders=50),
        _item(2008, "Doctor.Who.2023.S01E01.MULTi.1080p.WEB"),
        _item(2009, "Shogun.2024.S02E05.MULTi.1080p.CAM"),
        _item(3001, "Oppenheimer.2023.MULTi.1080p.BluRay", cats=("2000",)),
        _item(3002, "Daft.Punk-Discovery.FLAC", cats=("3010",)),
    ]
    entry = await _setup(hass, servers)
    assert entry.runtime_data.series is None

    # --- Dossiers par type
    result = await _options(hass, entry, "folders", {
        "path_movies": "/data/films", "cat_movies": "films",
        "path_series": "/data/series", "cat_series": "series",
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "c411/config"})
    cfg = (await ws.receive_json())["result"]
    folders = {f["type"]: f for f in cfg["folders"]}
    assert folders["movies"]["path"] == "/data/films" and folders["music"]["path"] == ""
    assert cfg["plex"] is False

    # Film → dossier films ; musique → dossier par défaut (rien de défini)
    base = servers["base"]
    await ws.send_json({"id": 2, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=3001",
                        "title": "Oppenheimer", "categories": ["2000"]})
    assert (await ws.receive_json())["success"]
    assert servers["added"][-1]["savepath"] == "/data/films" and servers["added"][-1]["category"] == "films"
    await ws.send_json({"id": 3, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=3002",
                        "title": "Daft Punk", "categories": ["3010"]})
    assert (await ws.receive_json())["success"]
    assert "savepath" not in servers["added"][-1] and "category" not in servers["added"][-1]
    # Catégorie explicite vide = aucune catégorie, mais dossier du type conservé
    await ws.send_json({"id": 4, "type": "c411/download", "url": f"{base}/api/torznab?t=get&id=3001",
                        "categories": ["2000"], "category": ""})
    assert (await ws.receive_json())["success"]
    assert "category" not in servers["added"][-1] and servers["added"][-1]["savepath"] == "/data/films"

    # --- Plex : mauvais jeton puis bon
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "plex"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "plex_url": servers["plex_base"], "plex_token": "nope", "plex_verify_ssl": True,
        "plex_refresh_on_complete": True,
    })
    assert result["errors"] == {"base": "invalid_plex_token"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "plex_url": servers["plex_base"] + "/", "plex_token": PLEX_TOKEN, "plex_verify_ssl": True,
        "plex_refresh_on_complete": True,
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    series = entry.runtime_data.series
    assert series is not None and series.data["server_name"] == "Serveur Maison"
    assert len(series.data["shows"]) == 3
    assert entry.options["path_series"] == "/data/series"  # les autres options sont conservées

    # Options du suivi : on coupe l'automatique pour tester le mode manuel d'abord
    result = await _options(hass, entry, "series", {
        "series_enabled": True, "series_auto": False, "series_follow_new": True, "plex_sections": [],
        "series_quality": "1080p", "series_qualities": ["1080p", "720p"], "series_languages": ["vf"],
        "series_min_seeders": 1, "series_exclude": "CAM, TS", "series_packs": True, "series_max_grabs": 5,
        "series_interval": 30, "plex_interval": 60, "series_notify": True,
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY
    series = entry.runtime_data.series
    ws = await hass_ws_client(hass)

    # --- Vérification : rien n'est téléchargé en mode manuel
    added_before = len(servers["added"])
    await ws.send_json({"id": 10, "type": "c411/series_check"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    shows = {s["title"]: s for s in msg["result"]["shows"]}
    shogun, sev, bdl = shows["Shōgun"], shows["Severance"], shows["Le Bureau des Légendes"]
    assert shogun["last"] == "S02E02" and shogun["episode_count"] == 12
    assert [a["key"] for a in shogun["available"]] == ["S02E03"]  # VOSTFR, 2160p, CAM et S02E02 écartés
    assert "AAA" in shogun["available"][0]["title"]
    assert [a["key"] for a in sev["available"]] == ["S03"]  # le pack remplace S03E01
    assert sev["last"] == "S02E09" and sev["season_count"] == 2  # saison 0 ignorée
    assert bdl["available"] == [] and bdl["status"] == "up_to_date"
    assert msg["result"]["available_count"] == 2
    assert len(servers["added"]) == added_before

    state = hass.states.get("sensor.plex_suivi_des_series_new_episodes_available")
    assert state is not None and state.state == "2", [s.entity_id for s in hass.states.async_all("sensor")]

    # --- Téléchargement manuel d'un épisode
    await ws.send_json({"id": 11, "type": "c411/series_grab", "rating_key": "100", "key": "S02E03"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    added = servers["added"][-1]
    assert added["savepath"] == "/data/series" and added["category"] == "series" and added["tags"] == "c411"
    shogun = next(s for s in msg["result"]["shows"] if s["rating_key"] == "100")
    assert shogun["status"] == "grabbed" and shogun["grabbed"][0]["code"] == "S02E03"
    # --- Ne plus suivre Severance puis passer en automatique
    await ws.send_json({"id": 12, "type": "c411/series_update", "rating_key": "102", "follow": False})
    assert (await ws.receive_json())["success"]

    events = []
    hass.bus.async_listen("c411_episode_grabbed", lambda e: events.append(e))
    servers["items"].append(_item(2010, "Shogun.2024.S02E04.MULTi.1080p.WEB.H264-GGG"))
    await _options(hass, entry, "series", {
        "series_enabled": True, "series_auto": True, "series_follow_new": True, "plex_sections": [],
        "series_quality": "1080p", "series_qualities": ["1080p", "720p"], "series_languages": ["vf"],
        "series_min_seeders": 1, "series_exclude": "CAM, TS", "series_packs": True, "series_max_grabs": 5,
        "series_interval": 30, "plex_interval": 60, "series_notify": True,
    })
    series = entry.runtime_data.series
    ws = await hass_ws_client(hass)
    n = len(servers["added"])
    await ws.send_json({"id": 20, "type": "c411/series_check", "rating_key": "100"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    await hass.async_block_till_done()
    assert len(servers["added"]) == n + 1  # S02E04 seulement (S02E03 déjà récupéré, Severance non suivie)
    assert [e.data["episode"] for e in events] == ["S02E04"] and events[0].data["automatic"] is True
    shows = {s["rating_key"]: s for s in msg["result"]["shows"]}
    assert {g["code"] for g in shows["100"]["grabbed"]} == {"S02E03", "S02E04"}
    assert shows["102"]["follow"] is False and shows["102"]["available"]  # trouvé mais pas téléchargé

    # --- Plex récupère S02E03 : il sort de la liste « récupérés »
    servers["plex_shows"]["100"]["owned"].append((2, 3))
    await series.async_refresh()
    shogun = next(s for s in series.data["shows"] if s["rating_key"] == "100")
    assert shogun["last"] == "S02E03" and [g["code"] for g in shogun["grabbed"]] == ["S02E04"]

    # --- Fin de téléchargement → Plex rescanne la bibliothèque des séries
    hass.bus.async_fire("c411_download_completed", {"name": "Shogun.2024.S02E04.MULTi.1080p", "from_c411": True})
    await hass.async_block_till_done()
    assert servers["plex_refreshed"] == ["1"]

    # --- Affiches
    client = await hass_client_no_auth()
    ok = await client.get(f"/api/c411/plex/poster/100?s={series.poster_secret}")
    assert ok.status == 200 and await ok.read() == PNG
    bad = await client.get("/api/c411/plex/poster/100?s=wrong")
    assert bad.status == 404

    # --- Service
    resp = await hass.services.async_call(DOMAIN, "check_series", {}, blocking=True, return_response=True)
    assert resp["available_count"] == 0

    # --- Persistance : les préférences survivent à un rechargement
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    series = entry.runtime_data.series
    shows = {s["rating_key"]: s for s in series.data["shows"]}
    assert shows["102"]["follow"] is False
    assert [g["code"] for g in shows["100"]["grabbed"]] == ["S02E04"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_next_seasons(hass: HomeAssistant, servers, hass_ws_client) -> None:
    """Série dont on n'a que la saison 1 : saisons suivantes téléchargées, une notification par saison."""
    servers["plex_shows"] = {
        "103": {"title": "Dark", "year": 2017, "guids": ["tmdb://70523"], "owned": [(1, e) for e in range(1, 11)]},
        "101": {"title": "Le Bureau des Légendes", "year": 2015, "guids": ["tmdb://62852"],
                "owned": [(s, e) for s in range(1, 6) for e in range(1, 11)]},
    }
    servers["items"] = [
        _item(5001, "Dark.S02.MULTi.1080p.NF.WEB-DL.DDP5.1-AAA", tmdbid="70523", seeders=80),
        _item(5002, "Dark.S03E01.MULTi.1080p.NF.WEB-DL-BBB"),
        _item(5003, "Dark.S03.MULTi.1080p.NF.WEB-DL.DDP5.1-CCC", seeders=60),
    ]
    notify_calls = []

    async def fake_notify(call):
        notify_calls.append(dict(call.data))

    hass.services.async_register("notify", "mobile_app_test", fake_notify)
    new_season_events = []
    hass.bus.async_listen("c411_new_season", lambda e: new_season_events.append(e.data))

    entry = await _setup(hass, servers)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "plex"})
    await hass.config_entries.options.async_configure(result["flow_id"], {
        "plex_url": servers["plex_base"], "plex_token": PLEX_TOKEN, "plex_verify_ssl": True,
        "plex_refresh_on_complete": True,
    })
    await hass.async_block_till_done()
    series_opts = {
        "series_enabled": True, "series_auto": True, "series_follow_new": True, "plex_sections": [],
        "series_quality": "1080p", "series_qualities": ["1080p", "720p"], "series_languages": ["vf"],
        "series_min_seeders": 1, "series_exclude": "CAM", "series_packs": True, "series_next_seasons": True,
        "series_max_grabs": 5, "series_interval": 30, "plex_interval": 60, "series_notify": True,
        "series_notify_service": "notify.mobile_app_test",
    }
    result = await _options(hass, entry, "series", series_opts)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    ws = await hass_ws_client(hass)

    # --- Vérification de Dark : saisons 2 et 3 en packs complets
    n = len(servers["added"])
    await ws.send_json({"id": 1, "type": "c411/series_check", "rating_key": "103"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    await hass.async_block_till_done()
    titles = [a["torrents"]["filename"] for a in servers["added"][n:]]
    assert titles == ["Dark.S02.MULTi.1080p.NF.WEB-DL.DDP5.1-AAA.torrent", "Dark.S03.MULTi.1080p.NF.WEB-DL.DDP5.1-CCC.torrent"]
    dark = next(s for s in msg["result"]["shows"] if s["rating_key"] == "103")
    assert dark["new_seasons"] == [2, 3] and {g["code"] for g in dark["grabbed"]} == {"S02", "S03"}

    # Une notification par saison (Home Assistant + téléphone), pas une par épisode
    assert [(e["season"], e["downloading"]) for e in new_season_events] == [(2, True), (3, True)]
    assert [c["title"] for c in notify_calls] == ["Nouvelle saison : Dark", "Nouvelle saison : Dark"]
    assert "saison 2" in notify_calls[0]["message"] and "**" not in notify_calls[0]["message"]

    # Nouvelle vérification : aucune nouvelle notification
    await ws.send_json({"id": 2, "type": "c411/series_check", "rating_key": "103"})
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert len(new_season_events) == 2 and len(notify_calls) == 2

    # --- Série à jour (5 saisons) : recherche précise de la saison 6 par identifiant
    await ws.send_json({"id": 3, "type": "c411/series_check", "rating_key": "101"})
    assert (await ws.receive_json())["success"]
    assert any(c.get("t") == "tvsearch" and c.get("tmdbid") == "62852" and c.get("season") == "6"
               for c in servers["c411_calls"])

    # --- Plex récupère les saisons 2 et 3 ; la saison 5 arrive alors que la 4 manque
    servers["plex_shows"]["103"]["owned"] += [(s, e) for s in (2, 3) for e in range(1, 9)]
    series = entry.runtime_data.series
    await series.async_refresh()
    servers["items"] += [
        _item(5004, "Dark.S05.MULTi.1080p.WEB-DL-DDD", seeders=40),
        _item(5005, "Dark.S04E01.MULTi.1080p.WEB-DL-EEE", seeders=40),
    ]
    # Rattrapage désactivé : seulement la saison suivante (4), pas la 5
    await _options(hass, entry, "series", {**series_opts, "series_next_seasons": False, "series_auto": False})
    series = entry.runtime_data.series
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 4, "type": "c411/series_check", "rating_key": "103"})
    msg = await ws.receive_json()
    await hass.async_block_till_done()
    dark = next(s for s in msg["result"]["shows"] if s["rating_key"] == "103")
    assert [a["key"] for a in dark["available"]] == ["S04E01"] and dark["new_seasons"] == [4]
    assert new_season_events[-1] == {"show": "Dark", "season": 4, "downloading": False, "rating_key": "103"}
    assert "à télécharger" in notify_calls[-1]["message"]
