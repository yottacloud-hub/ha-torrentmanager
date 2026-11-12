"""Faux serveurs C411 (Torznab) et qBittorrent pour les tests."""

from __future__ import annotations

from aiohttp import web

API_KEY = "secret-key"
TORRENT = b"d8:announce30:https://tracker.c411.org/announce4:infod4:name4:test6:lengthi1ee"

ITEMS = [
    {"id": "1001", "title": "Dune.Part.Two.2024.MULTi.2160p.WEB-DL.DV.HDR.H265-GRP", "date": "Wed, 11 Nov 2026 20:15:00 +0000",
     "size": 21474836480, "cats": ["2000", "2030"], "seeders": 154, "peers": 12, "grabs": 890,
     "infohash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "imdbid": "tt15239678", "free": True},
    {"id": "1002", "title": "Shogun.S02E03.FRENCH.1080p.WEB.H264-GRP", "date": "Thu, 12 Nov 2026 08:00:00 +0000",
     "size": 2147483648, "cats": ["5000"], "seeders": 40, "peers": 3, "grabs": 120,
     "infohash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
]


def render(items, base):
    out = []
    for it in items:
        attrs = "".join(f'<torznab:attr name="category" value="{c}"/>' for c in it["cats"])
        for k in ("seeders", "peers", "grabs", "infohash", "imdbid", "tmdbid"):
            if k in it:
                attrs += f'<torznab:attr name="{k}" value="{it[k]}"/>'
        attrs += f'<torznab:attr name="downloadvolumefactor" value="{0 if it.get("free") else 1}"/>'
        out.append(f"""<item><title>{it["title"]}</title><guid>https://c411.org/torrents/{it["id"]}</guid>
  <comments>https://c411.org/torrents/{it["id"]}</comments><pubDate>{it.get("date", "Thu, 12 Nov 2026 09:00:00 +0000")}</pubDate>
  <size>{it["size"]}</size><enclosure url="{base}/api/torznab?t=get&amp;id={it["id"]}" length="{it["size"]}" type="application/x-bittorrent"/>
  {attrs}</item>""")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">'
            f"<channel><title>C411</title>{''.join(out)}</channel></rss>")


def _matches(it, q, cats):
    title = it["title"].lower().replace(".", " ")
    if q and not all(w in title for w in q.lower().split()):
        return False
    if cats and not any(c == w or (w.endswith("000") and c[0] == w[0]) for c in it["cats"] for w in cats):
        return False
    return True


def make_c411_app(state: dict) -> web.Application:
    async def torznab(request: web.Request) -> web.Response:
        state.setdefault("c411_calls", []).append(dict(request.query))
        if request.query.get("apikey") != API_KEY:
            return web.Response(
                text='<?xml version="1.0"?><error code="100" description="Incorrect user credentials"/>',
                content_type="application/xml",
            )
        if request.query.get("t") == "get":
            if request.query.get("id") == "redirect":
                raise web.HTTPFound(f"{state['base']}/api/torznab?t=get&id=1001&apikey={API_KEY}")
            if request.query.get("id") == "magnet":
                raise web.HTTPFound("magnet:?xt=urn:btih:cccc")
            return web.Response(body=TORRENT, content_type="application/x-bittorrent")
        items = state.get("items", ITEMS)
        q = request.query.get("q", "")
        cats = [c for c in request.query.get("cat", "").split(",") if c]
        found = [it for it in items if _matches(it, q, cats)]
        return web.Response(text=render(found, state["base"]), content_type="application/rss+xml")

    app = web.Application()
    app.router.add_get("/api/torznab", torznab)
    return app


def make_qbit_app(state: dict, *, v5: bool = True) -> web.Application:
    state.setdefault("torrents", [
        {"hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "name": "Dune.Part.Two", "size": 100,
         "progress": 0.5, "dlspeed": 1000, "upspeed": 10, "eta": 50, "state": "downloading",
         "category": "films", "tags": "c411", "added_on": 1, "completion_on": 0, "num_seeds": 5,
         "num_leechs": 1, "ratio": 0.1, "save_path": "/dl", "amount_left": 50},
        {"hash": "dddd", "name": "Ubuntu ISO", "size": 100, "progress": 1, "dlspeed": 0,
         "upspeed": 0, "eta": 8640000, "state": "stalledUP", "category": "", "tags": "",
         "added_on": 0, "completion_on": 2, "num_seeds": 0, "num_leechs": 0, "ratio": 2,
         "save_path": "/dl", "amount_left": 0},
    ])
    state.setdefault("added", [])
    state.setdefault("actions", [])

    def authed(request: web.Request) -> bool:
        return request.cookies.get("SID") == "good-sid"

    async def login(request: web.Request) -> web.Response:
        data = await request.post()
        if request.headers.get("Referer", "").rstrip("/") != state["qb_base"]:
            return web.Response(status=401, text="Unauthorized")
        if data.get("username") == "admin" and data.get("password") == "pw":
            resp = web.Response(text="Ok.")
            resp.set_cookie("SID", "good-sid")
            return resp
        return web.Response(text="Fails.")

    def guard(handler):
        async def wrapped(request):
            if not authed(request):
                return web.Response(status=403, text="Forbidden")
            return await handler(request)
        return wrapped

    async def version(request):
        return web.Response(text="v5.0.1" if v5 else "v4.6.7")

    async def transfer(request):
        return web.json_response({"dl_info_speed": 2_500_000, "up_info_speed": 120_000, "connection_status": "connected"})

    async def info(request):
        return web.json_response(state["torrents"])

    async def categories(request):
        return web.json_response({"films": {}, "series": {}})

    async def add(request):
        reader = await request.multipart()
        fields = {}
        async for part in reader:
            if part.filename:
                fields[part.name] = {"filename": part.filename, "data": await part.read()}
            else:
                fields[part.name] = (await part.read()).decode()
        state["added"].append(fields)
        return web.Response(text="Ok.")

    def action(name):
        async def handler(request):
            data = await request.post()
            state["actions"].append((name, dict(data)))
            return web.Response(text="")
        return handler

    app = web.Application()
    app.router.add_post("/api/v2/auth/login", login)
    app.router.add_get("/api/v2/app/version", guard(version))
    app.router.add_get("/api/v2/transfer/info", guard(transfer))
    app.router.add_get("/api/v2/torrents/info", guard(info))
    app.router.add_get("/api/v2/torrents/categories", guard(categories))
    app.router.add_post("/api/v2/torrents/add", guard(add))
    app.router.add_post("/api/v2/torrents/delete", guard(action("delete")))
    for name in (("start", "stop") if v5 else ("resume", "pause")):
        app.router.add_post(f"/api/v2/torrents/{name}", guard(action(name)))
    return app


PLEX_TOKEN = "plex-token"
PNG = b"\x89PNG\r\n\x1a\nfake"


def make_plex_app(state: dict) -> web.Application:
    """Faux Plex : une bibliothèque de séries et une de films."""
    state.setdefault("plex_shows", {
        "100": {"title": "Shōgun", "year": 2024, "guids": ["tmdb://126308", "imdb://tt2788316"],
                "owned": [(1, e) for e in range(1, 11)] + [(2, 1), (2, 2)]},
        "101": {"title": "Le Bureau des Légendes", "year": 2015, "guids": ["tmdb://62852"],
                "owned": [(s, e) for s in range(1, 6) for e in range(1, 11)]},
        "102": {"title": "Severance", "year": 2022, "guids": ["tmdb://95396"],
                "owned": [(s, e) for s in (1, 2) for e in range(1, 10)] + [(0, 1)]},
    })
    state.setdefault("plex_refreshed", [])

    @web.middleware
    async def auth(request, handler):
        if request.headers.get("X-Plex-Token") != PLEX_TOKEN:
            return web.Response(status=401)
        return await handler(request)

    def mc(**kw):
        return web.json_response({"MediaContainer": kw})

    async def root(request):
        return mc(friendlyName="Serveur Maison")

    async def sections(request):
        return mc(Directory=[{"key": "1", "type": "show", "title": "Séries"},
                             {"key": "2", "type": "movie", "title": "Films"}])

    async def all_(request):
        if request.match_info["key"] != "1":
            return mc(Metadata=[])
        return mc(Metadata=[
            {"ratingKey": k, "title": v["title"], "year": v["year"], "thumb": f"/library/metadata/{k}/thumb/1",
             "leafCount": len(v["owned"]), "Guid": [{"id": g} for g in v["guids"]]}
            for k, v in state["plex_shows"].items()
        ])

    async def leaves(request):
        show = state["plex_shows"][request.match_info["key"]]
        return mc(Metadata=[{"parentIndex": s, "index": e} for s, e in show["owned"]])

    async def refresh(request):
        state["plex_refreshed"].append(request.match_info["key"])
        return web.Response(text="")

    async def transcode(request):
        return web.Response(body=PNG, content_type="image/png")

    app = web.Application(middlewares=[auth])
    app.router.add_get("/", root)
    app.router.add_get("/library/sections", sections)
    app.router.add_get("/library/sections/{key}/all", all_)
    app.router.add_get("/library/sections/{key}/refresh", refresh)
    app.router.add_get("/library/metadata/{key}/allLeaves", leaves)
    app.router.add_get("/photo/:/transcode", transcode)
    return app


TMDB_KEY = "tmdb-key"


def make_tmdb_app(state: dict) -> web.Application:
    """Faux TMDB v3."""
    state.setdefault("tmdb_calls", [])
    movies = {"693134": {"id": 693134, "title": "Dune : Deuxième partie", "release_date": "2024-02-28",
                         "poster_path": "/dune.jpg", "vote_average": 8.15}}
    tv = {"126308": {"id": 126308, "name": "Shōgun", "first_air_date": "2024-02-27",
                     "poster_path": "/shogun.jpg", "vote_average": 8.6}}

    @web.middleware
    async def auth(request, handler):
        state["tmdb_calls"].append(request.path)
        if request.query.get("api_key") != TMDB_KEY:
            return web.json_response({"status_message": "Invalid API key"}, status=401)
        return await handler(request)

    async def configuration(request):
        return web.json_response({"images": {}})

    async def movie(request):
        m = movies.get(request.match_info["id"])
        return web.json_response(m) if m else web.json_response({}, status=404)

    async def show(request):
        t = tv.get(request.match_info["id"])
        return web.json_response(t) if t else web.json_response({}, status=404)

    async def find(request):
        if request.match_info["imdb"] == "tt15239678":
            return web.json_response({"movie_results": [movies["693134"]], "tv_results": []})
        return web.json_response({"movie_results": [], "tv_results": []})

    async def search_movie(request):
        q = request.query.get("query", "")
        if "oppenheimer" in q:
            return web.json_response({"results": [{"id": 872585, "title": "Oppenheimer", "release_date": "2023-07-19",
                                                   "poster_path": "/opp.jpg", "vote_average": 8.1}]})
        return web.json_response({"results": []})

    app = web.Application(middlewares=[auth])
    app.router.add_get("/3/configuration", configuration)
    app.router.add_get("/3/movie/{id}", movie)
    app.router.add_get("/3/tv/{id}", show)
    app.router.add_get("/3/find/{imdb}", find)
    app.router.add_get("/3/search/movie", search_movie)
    async def search_tv(request):
        return web.json_response({"results": []})

    app.router.add_get("/3/search/tv", search_tv)
    return app
