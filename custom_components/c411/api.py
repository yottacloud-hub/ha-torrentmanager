"""Clients pour l'API Torznab de C411 et l'API Web de qBittorrent."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime
import logging
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import aiohttp

from .const import C411_MIN_REQUEST_INTERVAL
from .content import content_type

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_TORRENT_SIZE = 10 * 1024 * 1024  # 10 Mo : largement suffisant pour un .torrent


# ---------------------------------------------------------------------------
# Erreurs
# ---------------------------------------------------------------------------
class C411Error(Exception):
    """Erreur générique C411."""


class C411AuthError(C411Error):
    """Clé API refusée."""


class QBittorrentError(Exception):
    """Erreur générique qBittorrent."""


class QBittorrentAuthError(QBittorrentError):
    """Identifiants qBittorrent refusés."""


# ---------------------------------------------------------------------------
# C411
# ---------------------------------------------------------------------------
@dataclass
class C411Release:
    """Une release renvoyée par le flux Torznab."""

    guid: str
    title: str
    details_url: str | None
    download_url: str | None
    size: int = 0
    published: str | None = None
    categories: list[str] = field(default_factory=list)
    seeders: int = 0
    leechers: int = 0
    grabs: int = 0
    infohash: str | None = None
    imdbid: str | None = None
    tmdbid: str | None = None
    freeleech: bool = False
    content_type: str = "other"

    def as_dict(self) -> dict[str, Any]:
        """Version sérialisable."""
        return asdict(self)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_torznab(xml_text: str) -> list[C411Release]:
    """Transforme une réponse Torznab (RSS) en liste de releases."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise C411Error(f"Réponse XML invalide : {err}") from err

    if root.tag == "error":
        code = root.attrib.get("code", "")
        desc = root.attrib.get("description", "erreur inconnue")
        if code in {"100", "101", "102"}:
            raise C411AuthError(desc)
        raise C411Error(f"C411 a renvoyé l'erreur {code} : {desc}")

    releases: list[C411Release] = []
    for item in root.iter("item"):
        attrs: dict[str, list[str]] = {}
        for child in item:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "attr":
                name = child.attrib.get("name")
                if name is not None:
                    attrs.setdefault(name, []).append(child.attrib.get("value", ""))

        def first(name: str, _attrs: dict[str, list[str]] = attrs) -> str | None:
            vals = _attrs.get(name)
            return vals[0] if vals else None

        enclosure = item.find("enclosure")
        download_url = enclosure.attrib.get("url") if enclosure is not None else None
        if not download_url:
            download_url = item.findtext("link")

        published = None
        if pub := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(pub).isoformat()
            except (TypeError, ValueError):
                published = None

        categories = list(attrs.get("category", []))
        if not categories:
            categories = [c.text for c in item.findall("category") if c.text]

        size = _to_int(item.findtext("size"))
        if not size and enclosure is not None:
            size = _to_int(enclosure.attrib.get("length"))
        if not size:
            size = _to_int(first("size"))

        details = item.findtext("comments") or item.findtext("guid")
        if details and not details.startswith("http"):
            details = None

        infohash = first("infohash")
        releases.append(
            C411Release(
                guid=item.findtext("guid") or download_url or item.findtext("title") or "",
                title=(item.findtext("title") or "").strip(),
                details_url=details,
                download_url=download_url,
                size=size,
                published=published,
                categories=categories,
                seeders=_to_int(first("seeders")),
                leechers=_to_int(first("peers") or first("leechers")),
                grabs=_to_int(first("grabs")),
                infohash=infohash.lower() if infohash else None,
                imdbid=first("imdbid") or first("imdb"),
                tmdbid=first("tmdbid"),
                freeleech=first("downloadvolumefactor") in {"0", "0.0"},
                content_type=content_type(categories),
            )
        )
    return releases


class C411Client:
    """Client minimal pour l'API Torznab de C411."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, base_url: str) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._host = (urlparse(self._base_url).hostname or "").lower()
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    @property
    def base_url(self) -> str:
        """URL du site."""
        return self._base_url

    async def _throttle(self) -> None:
        """Respecte la limite de débit de C411 (≈15 req/min)."""
        async with self._lock:
            wait = C411_MIN_REQUEST_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    def is_own_url(self, url: str) -> bool:
        """Vérifie qu'une URL pointe bien vers C411 (évite d'utiliser HA comme proxy)."""
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and (
            host == self._host or host.endswith("." + self._host)
        )

    async def search(
        self,
        query: str = "",
        categories: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[C411Release]:
        """Recherche (ou derniers ajouts si `query` est vide)."""
        params: dict[str, Any] = {
            "apikey": self._api_key,
            "t": "search",
            "q": query.strip(),
            "limit": max(1, min(int(limit), 100)),
        }
        if offset:
            params["offset"] = int(offset)
        if categories:
            params["cat"] = ",".join(str(c) for c in categories)

        await self._throttle()
        try:
            async with self._session.get(
                f"{self._base_url}/api/torznab", params=params, timeout=REQUEST_TIMEOUT
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    raise C411AuthError("Clé API C411 refusée")
                if resp.status == 429:
                    raise C411Error("Limite de requêtes C411 atteinte, réessayez dans une minute")
                if resp.status >= 400:
                    raise C411Error(f"C411 a répondu HTTP {resp.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise C411Error(f"Impossible de joindre C411 : {err}") from err
        return parse_torznab(text)

    async def validate(self) -> None:
        """Vérifie la clé API."""
        await self.search(limit=1)

    def _with_apikey(self, url: str) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if "/api/" in parsed.path and "apikey" not in query:
            query["apikey"] = self._api_key
            return urlunparse(parsed._replace(query=urlencode(query)))
        return url

    async def fetch_torrent(self, url: str) -> tuple[bytes | None, str | None]:
        """Télécharge un .torrent. Renvoie (contenu, None) ou (None, lien magnet)."""
        if url.startswith("magnet:"):
            return None, url
        if not self.is_own_url(url):
            raise C411Error("Lien de téléchargement refusé : il ne pointe pas vers C411")

        current = self._with_apikey(url)
        for _ in range(5):
            await self._throttle()
            try:
                async with self._session.get(
                    current, allow_redirects=False, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status in (301, 302, 303, 307, 308):
                        location = resp.headers.get("Location", "")
                        if location.startswith("magnet:"):
                            return None, location
                        current = urljoin(current, location)
                        if not self.is_own_url(current):
                            raise C411Error("Redirection hors de C411 refusée")
                        continue
                    if resp.status in (401, 403):
                        raise C411AuthError("C411 refuse le téléchargement (clé API ?)")
                    if resp.status == 429:
                        raise C411Error("Limite de requêtes C411 atteinte, réessayez dans une minute")
                    if resp.status >= 400:
                        raise C411Error(f"Téléchargement du .torrent : HTTP {resp.status}")
                    data = await resp.content.read(MAX_TORRENT_SIZE + 1)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise C411Error(f"Impossible de récupérer le .torrent : {err}") from err

            if len(data) > MAX_TORRENT_SIZE:
                raise C411Error("Fichier .torrent anormalement volumineux")
            if not data.startswith(b"d"):
                # Un .torrent est un dictionnaire bencodé : il commence par « d ».
                snippet = data[:200].decode("utf-8", "replace")
                if "<error" in snippet:
                    parse_torznab(snippet)  # lève l'erreur détaillée
                raise C411Error("La réponse de C411 n'est pas un fichier .torrent")
            return data, None
        raise C411Error("Trop de redirections")


# ---------------------------------------------------------------------------
# qBittorrent
# ---------------------------------------------------------------------------
TORRENT_FIELDS = (
    "hash",
    "name",
    "size",
    "total_size",
    "progress",
    "dlspeed",
    "upspeed",
    "eta",
    "state",
    "category",
    "tags",
    "added_on",
    "completion_on",
    "num_seeds",
    "num_leechs",
    "ratio",
    "save_path",
    "amount_left",
)


class QBittorrentClient:
    """Client pour l'API Web v2 de qBittorrent (v4.1+ et v5)."""

    def __init__(
        self, session: aiohttp.ClientSession, url: str, username: str, password: str
    ) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._username = username or ""
        self._password = password or ""
        self._logged_in = False
        self._login_lock = asyncio.Lock()
        self._uses_start_stop: bool | None = None

    @property
    def url(self) -> str:
        """URL de l'interface web."""
        return self._url

    @property
    def _headers(self) -> dict[str, str]:
        # qBittorrent vérifie Referer/Origin (protection CSRF)
        return {"Referer": self._url + "/", "Origin": self._url}

    async def login(self) -> None:
        """Ouvre une session (cookie SID)."""
        async with self._login_lock:
            try:
                async with self._session.post(
                    f"{self._url}/api/v2/auth/login",
                    data={"username": self._username, "password": self._password},
                    headers=self._headers,
                    timeout=REQUEST_TIMEOUT,
                ) as resp:
                    text = (await resp.text()).strip()
                    if resp.status == 403:
                        raise QBittorrentAuthError(
                            "IP bannie par qBittorrent (trop d'échecs de connexion)"
                        )
                    if resp.status >= 400:
                        raise QBittorrentError(f"qBittorrent a répondu HTTP {resp.status}")
                    if text.lower().startswith("fails"):
                        raise QBittorrentAuthError("Identifiants qBittorrent incorrects")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise QBittorrentError(f"Impossible de joindre qBittorrent : {err}") from err
            self._logged_in = True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        expect_json: bool = False,
        _retry: bool = True,
    ) -> Any:
        if not self._logged_in:
            await self.login()
        try:
            async with self._session.request(
                method,
                f"{self._url}/api/v2/{path}",
                params=params,
                data=data,
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403) and _retry:
                    self._logged_in = False
                    if isinstance(data, aiohttp.FormData):
                        raise QBittorrentError("Session expirée, réessayez")
                    return await self._request(
                        method, path, params=params, data=data,
                        expect_json=expect_json, _retry=False,
                    )
                if resp.status == 404:
                    raise _NotFound(path)
                if resp.status in (401, 403):
                    raise QBittorrentAuthError("Accès refusé par qBittorrent")
                if resp.status == 415:
                    raise QBittorrentError("qBittorrent : fichier torrent invalide")
                if resp.status >= 400:
                    raise QBittorrentError(
                        f"qBittorrent ({path}) : HTTP {resp.status} {await resp.text()}"
                    )
                if expect_json:
                    return await resp.json(content_type=None)
                return await resp.text()
        except RuntimeError as err:  # session fermée pendant un rechargement
            raise QBittorrentError(str(err)) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise QBittorrentError(f"Impossible de joindre qBittorrent : {err}") from err

    async def version(self) -> str:
        """Version de qBittorrent."""
        return (await self._request("GET", "app/version")).strip()

    async def webapi_version(self) -> str:
        """Version de l'API Web."""
        return (await self._request("GET", "app/webapiVersion")).strip()

    async def transfer_info(self) -> dict[str, Any]:
        """Vitesses globales."""
        return await self._request("GET", "transfer/info", expect_json=True)

    async def torrents(self) -> list[dict[str, Any]]:
        """Liste des torrents, champs utiles uniquement."""
        raw = await self._request(
            "GET", "torrents/info", params={"sort": "added_on", "reverse": "true"},
            expect_json=True,
        )
        result = []
        for tor in raw or []:
            item = {k: tor.get(k) for k in TORRENT_FIELDS}
            item["tags"] = [t.strip() for t in (tor.get("tags") or "").split(",") if t.strip()]
            item["hash"] = (item["hash"] or "").lower()
            result.append(item)
        return result

    async def categories(self) -> list[str]:
        """Catégories définies dans qBittorrent."""
        try:
            data = await self._request("GET", "torrents/categories", expect_json=True)
        except QBittorrentError:
            return []
        return sorted((data or {}).keys())

    async def add_torrent(
        self,
        *,
        torrent: bytes | None = None,
        magnet: str | None = None,
        filename: str = "c411.torrent",
        category: str | None = None,
        save_path: str | None = None,
        tags: str | None = None,
        paused: bool = False,
    ) -> None:
        """Ajoute un torrent (fichier ou magnet)."""

        def build() -> aiohttp.FormData:
            form = aiohttp.FormData(default_to_multipart=True)
            if torrent is not None:
                form.add_field(
                    "torrents", torrent, filename=filename,
                    content_type="application/x-bittorrent",
                )
            elif magnet:
                form.add_field("urls", magnet)
            else:
                raise QBittorrentError("Rien à ajouter")
            if category:
                form.add_field("category", category)
            if save_path:
                form.add_field("savepath", save_path)
            if tags:
                form.add_field("tags", tags)
            # « paused » pour v4, « stopped » pour v5
            form.add_field("paused", "true" if paused else "false")
            form.add_field("stopped", "true" if paused else "false")
            return form

        if not self._logged_in:
            await self.login()
        try:
            text = await self._request("POST", "torrents/add", data=build())
        except QBittorrentError as err:
            if "Session expirée" not in str(err):
                raise
            await self.login()
            text = await self._request("POST", "torrents/add", data=build())
        if isinstance(text, str) and text.strip().lower().startswith("fails"):
            raise QBittorrentError("qBittorrent a refusé le torrent (déjà présent ?)")

    async def _start_stop(self, start: bool, hashes: str) -> None:
        new, old = ("start", "resume") if start else ("stop", "pause")
        order = [new, old] if self._uses_start_stop is not False else [old, new]
        last_err: Exception | None = None
        for action in order:
            try:
                await self._request("POST", f"torrents/{action}", data={"hashes": hashes})
            except _NotFound as err:
                last_err = err
                continue
            self._uses_start_stop = action in ("start", "stop")
            return
        raise QBittorrentError(f"Action non supportée par qBittorrent : {last_err}")

    async def action(self, action: str, hashes: list[str]) -> None:
        """pause / resume / delete / delete_files / recheck / reannounce."""
        joined = "|".join(hashes)
        if action == "pause":
            await self._start_stop(False, joined)
        elif action == "resume":
            await self._start_stop(True, joined)
        elif action in ("delete", "delete_files"):
            await self._request(
                "POST", "torrents/delete",
                data={"hashes": joined, "deleteFiles": "true" if action == "delete_files" else "false"},
            )
        elif action in ("recheck", "reannounce"):
            await self._request("POST", f"torrents/{action}", data={"hashes": joined})
        else:
            raise QBittorrentError(f"Action inconnue : {action}")


class _NotFound(QBittorrentError):
    """Point d'API absent (différence v4/v5)."""
