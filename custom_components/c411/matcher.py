"""Analyse des noms de releases et choix du meilleur épisode."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

_EP_RE = re.compile(
    r"""^(?P<name>.+?)[\s._\-\[\(]+
        (?:(?P<year>(?:19|20)\d{2})[\s._\-\]\)]+)?
        S(?P<season>\d{1,2})
        (?:[\s._\-]?E(?P<ep>\d{1,3})(?:(?:[\s._\-]?E|-E?)(?P<ep2>\d{1,3}))?)?
        (?!\d)""",
    re.IGNORECASE | re.VERBOSE,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

VF_TOKENS = {"MULTI", "FRENCH", "TRUEFRENCH", "VFF", "VF2", "VFQ", "VFI", "VF", "VOF", "VQ"}
VOSTFR_TOKENS = {"VOSTFR", "SUBFRENCH", "STFR"}


def normalize(text: str) -> str:
    """« Le Bureau des Légendes (2015) » → « le bureau des legendes 2015 »."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " and ").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def show_keys(title: str, year: int | None = None) -> set[str]:
    """Formes normalisées acceptées pour un titre de série."""
    base = normalize(title)
    keys = {base}
    # « Titre (2019) » / « Titre 2019 » dans Plex
    stripped = re.sub(r"\s(19|20)\d{2}$", "", base)
    keys.add(stripped)
    if year:
        keys.add(f"{stripped} {year}")
    for prefix in ("the ", "le ", "la ", "les "):
        if stripped.startswith(prefix):
            keys.add(stripped[len(prefix):])
    return {k for k in keys if k}


@dataclass
class ParsedRelease:
    """Ce qu'on sait d'une release de série."""

    name: str
    year: int | None
    season: int
    episodes: list[int] = field(default_factory=list)
    quality: str = "sd"
    languages: str = "vo"
    multi: bool = False
    tokens: set[str] = field(default_factory=set)

    @property
    def is_pack(self) -> bool:
        return not self.episodes

    @property
    def codes(self) -> list[str]:
        return [code(self.season, e) for e in self.episodes]

    def keys(self) -> set[str]:
        keys = {self.name}
        if self.year:
            keys.add(f"{self.name} {self.year}")
        for prefix in ("the ", "le ", "la ", "les "):
            if self.name.startswith(prefix):
                keys.add(self.name[len(prefix):])
        return keys


def code(season: int, episode: int) -> str:
    """S02E06."""
    return f"S{season:02d}E{episode:02d}"


def parse_release(title: str) -> ParsedRelease | None:
    """Analyse « Shogun.2024.S02E03.MULTi.1080p.WEB.H264-GRP »."""
    m = _EP_RE.match(title.strip())
    if not m:
        return None
    eps: list[int] = []
    if m.group("ep"):
        first = int(m.group("ep"))
        last = int(m.group("ep2")) if m.group("ep2") else first
        if last < first or last - first > 30:
            last = first
        eps = list(range(first, last + 1))

    tokens = {t.upper() for t in _TOKEN_RE.findall(title)}
    low = title.lower()
    if re.search(r"(2160p|\b4k\b|\buhd\b)", low):
        quality = "2160p"
    elif "1080p" in low or "1080i" in low:
        quality = "1080p"
    elif "720p" in low:
        quality = "720p"
    else:
        quality = "sd"

    if tokens & VF_TOKENS:
        languages = "vf"
    elif tokens & VOSTFR_TOKENS:
        languages = "vostfr"
    else:
        languages = "vo"

    return ParsedRelease(
        name=normalize(m.group("name")),
        year=int(m.group("year")) if m.group("year") else None,
        season=int(m.group("season")),
        episodes=eps,
        quality=quality,
        languages=languages,
        multi="MULTI" in tokens,
        tokens=tokens,
    )


@dataclass
class Rules:
    """Préférences de téléchargement automatique."""

    quality: str = "1080p"
    qualities: list[str] = field(default_factory=lambda: ["1080p", "720p"])
    languages: list[str] = field(default_factory=lambda: ["vf"])
    min_seeders: int = 1
    exclude: list[str] = field(default_factory=list)
    packs: bool = True


def score(parsed: ParsedRelease, release: dict[str, Any], rules: Rules) -> int | None:
    """Note une release ; None si elle ne respecte pas les règles."""
    if parsed.quality not in rules.qualities and parsed.quality != rules.quality:
        return None
    if parsed.languages not in rules.languages:
        return None
    if (release.get("seeders") or 0) < rules.min_seeders:
        return None
    if any(word.upper() in parsed.tokens for word in rules.exclude):
        return None
    if parsed.is_pack and not rules.packs:
        return None

    points = 1000 if parsed.quality == rules.quality else 500
    # langue : ordre de préférence de la liste, MULTi en bonus
    points += (len(rules.languages) - rules.languages.index(parsed.languages)) * 50
    if parsed.multi:
        points += 30
    if "PROPER" in parsed.tokens or "REPACK" in parsed.tokens:
        points += 20
    if release.get("freeleech"):
        points += 10
    points += min(int(release.get("seeders") or 0), 200) // 10
    return points


def match_show(
    parsed: ParsedRelease, release: dict[str, Any], shows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Trouve la série Plex correspondant à une release."""
    tmdb = str(release.get("tmdbid") or "")
    imdb = str(release.get("imdbid") or "")
    if imdb and not imdb.startswith("tt"):
        imdb = f"tt{int(imdb):07d}" if imdb.isdigit() else imdb
    for show in shows:
        guids = show.get("guids", {})
        if (tmdb and guids.get("tmdb") == tmdb) or (imdb and guids.get("imdb") == imdb):
            return show
    rkeys = parsed.keys()
    candidates = [s for s in shows if rkeys & s["keys"]]
    if parsed.year:
        # « Doctor.Who.2023 » ne doit pas tomber sur « Doctor Who » (2005)
        candidates = [
            s for s in candidates if not s.get("year") or abs(int(s["year"]) - parsed.year) <= 1
        ]
    elif len(candidates) > 1:
        # sans année dans le nom : on évite de deviner entre deux homonymes
        return None
    return candidates[0] if candidates else None
