"""Contenu adulte, regroupement des versions, affiches, droits des utilisateurs, nom."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

import custom_components.c411.const as const

from .fakes import ITEMS, TMDB_KEY
from .test_integration import _setup
from .test_series import _item, _options


async def test_display_and_access(
    hass: HomeAssistant, servers, hass_ws_client, hass_read_only_access_token, monkeypatch
) -> None:
    monkeypatch.setattr(const, "TMDB_API", f"{servers['tmdb_base']}/3")
    servers["items"] = ITEMS + [
        _item(4001, "Dune.Part.Two.2024.MULTi.1080p.BluRay.x264-AAA", cats=("2000",), seeders=300, grabs=4000,
              imdbid="tt15239678"),
        _item(4002, "Dune.Part.Two.2024.VOSTFR.1080p.WEB-DL-BBB", cats=("2000",), seeders=500),
        _item(4003, "Oppenheimer.2023.MULTi.1080p.BluRay", cats=("2000",)),
        _item(4004, "Some.Adult.Movie.2024.1080p", cats=("6010",)),
        _item(4005, "XXX.Compilation", cats=()),
        _item(4006, "xXx.2002.MULTi.1080p.BluRay", cats=("2000",)),
    ]
    entry = await _setup(hass, servers)
    assert entry.title == "TorrentManager"
    assert hass.data["frontend_panels"]["c411"].sidebar_title == "TorrentManager"
    assert hass.data["frontend_panels"]["c411"].require_admin is False  # accès par défaut : consultation + téléchargement

    # --- Contenu adulte masqué par défaut (mais pas le film « xXx »)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "c411/search", "query": ""})
    msg = await ws.receive_json()
    titles = [r["title"] for r in msg["result"]["results"]]
    assert msg["result"]["raw_count"] == 8 and len(titles) == 6
    assert "xXx.2002.MULTi.1080p.BluRay" in titles and not any("Adult" in t or "Compilation" in t for t in titles)
    feed = [r["title"] for r in entry.runtime_data.feed.data]
    assert not any("Adult" in t for t in feed)

    # --- Infos de version / regroupement
    by_title = {r["title"]: r for r in msg["result"]["results"]}
    dune4k = by_title["Dune.Part.Two.2024.MULTi.2160p.WEB-DL.DV.HDR.H265-GRP"]["info"]
    dune1080 = by_title["Dune.Part.Two.2024.MULTi.1080p.BluRay.x264-AAA"]["info"]
    assert dune4k["group"] == dune1080["group"] == "movie|dune part two|2024"
    assert dune4k["quality"] == "2160p" and dune4k["hdr"] == ["DV", "HDR"] and dune1080["source"] == "bluray"
    assert by_title["Shogun.S02E03.FRENCH.1080p.WEB.H264-GRP"]["info"]["group"] == "tv|shogun||02|03"

    # --- Options « Affichage » : clé TMDB refusée, puis acceptée ; adulte visible
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "display"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "hide_adult": False, "best_only": True, "pref_quality": "2160p", "pref_language": "vf",
        "tmdb_api_key": "bad", "user_access": "download",
    })
    assert result["errors"] == {"base": "invalid_tmdb_key"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "hide_adult": False, "best_only": True, "pref_quality": "2160p", "pref_language": "vf",
        "tmdb_api_key": TMDB_KEY, "user_access": "download",
    })
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.tmdb is not None

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 2, "type": "c411/search", "query": ""})
    assert len((await ws.receive_json())["result"]["results"]) == 8
    await ws.send_json({"id": 3, "type": "c411/config"})
    cfg = (await ws.receive_json())["result"]
    assert cfg["pref_quality"] == "2160p" and cfg["tmdb"] is True and cfg["permissions"]["manage"] is True

    # --- Affiches TMDB (id TMDB, id IMDb, recherche par titre) + cache
    items = [
        {"key": "a", "group": "movie|dune part two|2024", "kind": "movie", "name": "dune part two", "year": 2024,
         "imdbid": "tt15239678", "content_type": "movies"},
        {"key": "b", "group": "movie|oppenheimer|2023", "kind": "movie", "name": "oppenheimer", "year": 2023,
         "content_type": "movies"},
        {"key": "c", "group": "tv|shogun|2024|02|03", "kind": "episode", "name": "shogun", "year": 2024,
         "season": 2, "tmdbid": "126308", "content_type": "series"},
        {"key": "d", "group": "movie|inconnu|", "kind": "movie", "name": "inconnu", "content_type": "movies"},
    ]
    await ws.send_json({"id": 4, "type": "c411/artwork", "items": items})
    msg = await ws.receive_json()
    assert msg["success"], msg
    art = msg["result"]["artwork"]
    assert art["a"]["poster"].endswith("/dune.jpg") and art["a"]["title"] == "Dune : Deuxième partie"
    assert art["b"]["year"] == 2023 and art["c"]["vote"] == 8.6 and art["d"] is None
    n = len(servers["tmdb_calls"])
    await ws.send_json({"id": 5, "type": "c411/artwork", "items": items})
    assert (await ws.receive_json())["success"]
    assert len(servers["tmdb_calls"]) == n  # tout vient du cache

    # --- Utilisateur non administrateur : consultation + téléchargement
    user_ws = await hass_ws_client(hass, hass_read_only_access_token)
    await user_ws.send_json({"id": 1, "type": "c411/config"})
    perms = (await user_ws.receive_json())["result"]["permissions"]
    assert perms == {"view": True, "download": True, "manage": False}
    await user_ws.send_json({"id": 2, "type": "c411/download", "url": f"{servers['base']}/api/torznab?t=get&id=4003",
                             "categories": ["2000"]})
    assert (await user_ws.receive_json())["success"]
    await user_ws.send_json({"id": 3, "type": "c411/torrent_action", "action": "pause", "hashes": ["a" * 40]})
    assert (await user_ws.receive_json())["success"]
    await user_ws.send_json({"id": 4, "type": "c411/torrent_action", "action": "delete_files", "hashes": ["dddd"]})
    msg = await user_ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "unauthorized"

    # --- Consultation seule
    await _options(hass, entry, "display", {
        "hide_adult": True, "best_only": True, "pref_quality": "1080p", "pref_language": "vf",
        "tmdb_api_key": TMDB_KEY, "user_access": "view",
    })
    user_ws = await hass_ws_client(hass, hass_read_only_access_token)
    await user_ws.send_json({"id": 1, "type": "c411/search", "query": "dune"})
    assert (await user_ws.receive_json())["success"]
    await user_ws.send_json({"id": 2, "type": "c411/download", "url": f"{servers['base']}/api/torznab?t=get&id=4003"})
    assert (await user_ws.receive_json())["error"]["code"] == "unauthorized"

    # --- Administrateurs uniquement : panneau masqué
    await _options(hass, entry, "display", {
        "hide_adult": True, "best_only": True, "pref_quality": "1080p", "pref_language": "vf",
        "tmdb_api_key": TMDB_KEY, "user_access": "admins",
    })
    assert hass.data["frontend_panels"]["c411"].require_admin is True
    user_ws = await hass_ws_client(hass, hass_read_only_access_token)
    await user_ws.send_json({"id": 1, "type": "c411/config"})
    assert (await user_ws.receive_json())["error"]["code"] == "unauthorized"


async def test_recommendations(hass: HomeAssistant, servers, hass_ws_client, monkeypatch) -> None:
    monkeypatch.setattr(const, "TMDB_API", f"{servers['tmdb_base']}/3")
    entry = await _setup(hass, servers)
    ws = await hass_ws_client(hass)

    # Sans clé TMDB : non configuré
    await ws.send_json({"id": 1, "type": "c411/recommendations"})
    assert (await ws.receive_json())["result"]["configured"] is False

    await _options(hass, entry, "display", {
        "hide_adult": True, "best_only": True, "pref_quality": "1080p", "pref_language": "vf",
        "tmdb_api_key": TMDB_KEY, "user_access": "download",
    })
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 2, "type": "c411/recommendations"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    res = msg["result"]
    assert [s["title"] for s in res["seeds"]] == ["Dune : Deuxième partie"]
    titles = [i["title"] for i in res["items"]]
    assert titles[:3] == ["Dune", "Blade Runner 2049", "Oppenheimer"]
    assert "Dune : Deuxième partie" not in titles  # déjà téléchargé
    assert res["items"][0]["because"] == ["Dune : Deuxième partie"] and res["items"][0]["poster"].endswith("/dune1.jpg")

    # Cache : pas de nouvel appel TMDB
    n = len(servers["tmdb_calls"])
    await ws.send_json({"id": 3, "type": "c411/recommendations"})
    assert (await ws.receive_json())["success"] and len(servers["tmdb_calls"]) == n

    # Recherche C411 par identifiant TMDB, puis repli sur le titre
    await ws.send_json({"id": 4, "type": "c411/search", "query": "Dune Part Two", "tmdbid": 693134, "media": "movie"})
    msg = await ws.receive_json()
    assert [r["title"] for r in msg["result"]["results"]] == [ITEMS[0]["title"]]
    assert servers["c411_calls"][-1]["t"] == "movie" and servers["c411_calls"][-1]["tmdbid"] == "693134"
    await ws.send_json({"id": 5, "type": "c411/search", "query": "shogun", "tmdbid": 999, "media": "tv"})
    msg = await ws.receive_json()
    assert [r["title"] for r in msg["result"]["results"]] == [ITEMS[1]["title"]]
    assert servers["c411_calls"][-2]["t"] == "tvsearch" and servers["c411_calls"][-1]["q"] == "shogun"
