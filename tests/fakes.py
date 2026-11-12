"""Faux serveurs C411 (Torznab) et qBittorrent pour les tests."""

from __future__ import annotations

from aiohttp import web

API_KEY = "secret-key"
TORRENT = b"d8:announce30:https://tracker.c411.org/announce4:infod4:name4:test6:lengthi1ee"

TORZNAB = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:torznab="http://torznab.com/schemas/2015/feed">
<channel><title>C411</title>
<item>
  <title>Dune.Part.Two.2024.MULTi.2160p.WEB-DL.DV.HDR.H265-GRP</title>
  <guid>https://c411.org/torrents/1001</guid>
  <link>{base}/api/torznab?t=get&amp;id=1001</link>
  <comments>https://c411.org/torrents/1001</comments>
  <pubDate>Wed, 11 Nov 2026 20:15:00 +0000</pubDate>
  <size>21474836480</size>
  <enclosure url="{base}/api/torznab?t=get&amp;id=1001" length="21474836480" type="application/x-bittorrent"/>
  <torznab:attr name="category" value="2000"/>
  <torznab:attr name="category" value="2030"/>
  <torznab:attr name="seeders" value="154"/>
  <torznab:attr name="peers" value="12"/>
  <torznab:attr name="grabs" value="890"/>
  <torznab:attr name="infohash" value="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"/>
  <torznab:attr name="imdbid" value="tt15239678"/>
  <torznab:attr name="downloadvolumefactor" value="0"/>
</item>
<item>
  <title>Shogun.S02E03.FRENCH.1080p.WEB.H264-GRP</title>
  <guid>https://c411.org/torrents/1002</guid>
  <comments>https://c411.org/torrents/1002</comments>
  <pubDate>Thu, 12 Nov 2026 08:00:00 +0000</pubDate>
  <size>2147483648</size>
  <enclosure url="{base}/api/torznab?t=get&amp;id=1002" length="2147483648" type="application/x-bittorrent"/>
  <torznab:attr name="category" value="5000"/>
  <torznab:attr name="seeders" value="40"/>
  <torznab:attr name="peers" value="3"/>
  <torznab:attr name="grabs" value="120"/>
  <torznab:attr name="infohash" value="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"/>
  <torznab:attr name="downloadvolumefactor" value="1"/>
</item>
</channel></rss>"""


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
        return web.Response(text=TORZNAB.format(base=state["base"]), content_type="application/rss+xml")

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
