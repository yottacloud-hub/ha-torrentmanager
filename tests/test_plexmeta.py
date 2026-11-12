"""Affiches et recommandations via le catalogue Plex (sans TMDB)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

import custom_components.c411.plexmeta as plexmeta

from .fakes import DUNE2, META_IMAGE, PLEX_TOKEN
from .test_integration import _setup


async def _with_plex(hass, servers):
    entry = await _setup(hass, servers)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "plex"})
    await hass.config_entries.options.async_configure(result["flow_id"], {
        "plex_url": servers["plex_base"], "plex_token": PLEX_TOKEN, "plex_verify_ssl": True,
        "plex_refresh_on_complete": True,
    })
    await hass.async_block_till_done()
    return entry


async def test_plex_artwork_and_recommendations(
    hass: HomeAssistant, servers, hass_ws_client, hass_client_no_auth, monkeypatch
) -> None:
    monkeypatch.setattr(plexmeta, "DISCOVER", servers["plex_online_base"])
    monkeypatch.setattr(plexmeta, "METADATA", servers["plex_online_base"])
    entry = await _with_plex(hass, servers)
    rt = entry.runtime_data
    assert rt.plex_meta is not None and rt.tmdb is None

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "c411/config"})
    cfg = (await ws.receive_json())["result"]
    assert cfg["artwork"] is True and cfg["tmdb"] is False

    # --- Affiches depuis le catalogue Plex
    items = [
        {"key": "a", "group": "movie|dune part two|2024", "kind": "movie", "name": "dune part two", "year": 2024, "content_type": "movies"},
        {"key": "b", "group": "tv|shogun|2024|02|03", "kind": "episode", "name": "shogun", "year": 2024, "season": 2, "content_type": "series"},
        {"key": "c", "group": "movie|le comte de monte cristo|2024", "kind": "movie", "name": "le comte de monte cristo", "year": 2024, "content_type": "movies"},
        {"key": "d", "group": "movie|dune|1984", "kind": "movie", "name": "dune", "year": 1984, "content_type": "movies"},
    ]
    await ws.send_json({"id": 2, "type": "c411/artwork", "items": items})
    msg = await ws.receive_json()
    assert msg["success"], msg
    art = msg["result"]["artwork"]
    assert art["a"]["poster"] == "https://metadata-static.plex.tv/dune2.jpg" and art["a"]["title"] == "Dune : Deuxième partie"
    assert art["a"]["vote"] == 8.2 and art["a"]["tmdbid"] == "693134"
    assert art["b"]["poster"] == "https://metadata-static.plex.tv/shogun.jpg"
    # Année trop éloignée (Dune 1984 ≠ 2021) : pas d'affiche plutôt qu'une mauvaise
    assert "d" not in art or not (art["d"] or {}).get("poster", "").startswith("https://metadata-static.plex.tv/dune1")
    # Image relative : servie par Home Assistant, jeton caché
    rel = art["c"]["poster"]
    assert rel.startswith("/api/c411/plex/meta-image?") and PLEX_TOKEN not in rel
    client = await hass_client_no_auth()
    resp = await client.get(rel)
    assert resp.status == 200 and await resp.read() == META_IMAGE
    assert (await client.get(rel.replace("&s=", "&s=x"))).status == 404

    # Cache : pas de nouvel appel au catalogue
    n = len(servers["plex_online_calls"])
    await ws.send_json({"id": 3, "type": "c411/artwork", "items": items[:3]})
    assert (await ws.receive_json())["success"] and len(servers["plex_online_calls"]) == n

    # --- Recommandations via Plex
    await ws.send_json({"id": 4, "type": "c411/recommendations"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    res = msg["result"]
    assert res["configured"] and res["provider"] == "plex"
    assert [s["title"] for s in res["seeds"]][:2] == ["Dune : Deuxième partie", "Shōgun"]
    titles = [i["title"] for i in res["items"]]
    assert {"Dune", "Blade Runner 2049", "The Last Kingdom"} <= set(titles)
    assert "Dune : Deuxième partie" not in titles and "Shōgun" not in titles  # déjà possédés
    tlk = next(i for i in res["items"] if i["title"] == "The Last Kingdom")
    assert tlk["because"] == ["Shōgun"] and tlk["poster"].endswith("/tlk.jpg") and tlk["media"] == "tv"
    assert any(c.startswith(f"/library/metadata/{DUNE2}/related") for c in servers["plex_online_calls"])
