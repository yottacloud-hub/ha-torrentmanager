"""Analyse générique d'un nom de release (film, épisode, autre).

Sert à regrouper les différentes versions d'un même contenu et à les comparer.
"""

from __future__ import annotations

import re
from typing import Any

from .matcher import VF_TOKENS, VOSTFR_TOKENS, normalize, parse_release

_SPLIT_RE = re.compile(r"[\s._\[\]\(\)\-]+")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")

QUALITY_TOKENS = {"2160P": "2160p", "4K": "2160p", "UHD": "2160p", "1080P": "1080p", "1080I": "1080p",
                  "720P": "720p", "576P": "sd", "480P": "sd", "DVDRIP": "sd"}
SOURCE_TOKENS = {
    "REMUX": "remux", "BLURAY": "bluray", "BDRIP": "bluray", "BRRIP": "bluray", "BD": "bluray",
    "WEB": "web", "WEBDL": "web", "WEBRIP": "webrip", "HDTV": "hdtv", "TVRIP": "hdtv",
    "DVDRIP": "dvd", "DVD": "dvd", "HDLIGHT": "light", "MHD": "light", "4KLIGHT": "light",
    "CAM": "cam", "HDCAM": "cam", "TS": "cam", "HDTS": "cam", "TELESYNC": "cam",
}
SOURCE_PRIORITY = ["cam", "remux", "bluray", "web", "webrip", "light", "hdtv", "dvd"]
CODEC_TOKENS = {"X265": "x265", "H265": "x265", "HEVC": "x265", "X264": "x264", "H264": "x264",
                "AV1": "av1", "AVC": "x264"}
HDR_TOKENS = {"HDR": "HDR", "HDR10": "HDR", "HDR10PLUS": "HDR10+", "DV": "DV", "DOVI": "DV", "DOLBYVISION": "DV"}
LANG_TOKENS = VF_TOKENS | VOSTFR_TOKENS | {"ENGLISH", "VO", "VOST", "SUBFRENCH"}
STOP_TOKENS = (
    set(QUALITY_TOKENS) | set(SOURCE_TOKENS) | set(CODEC_TOKENS) | set(HDR_TOKENS) | LANG_TOKENS
    | {"COMPLETE", "INTEGRALE", "PROPER", "REPACK", "EXTENDED", "UNRATED", "REMASTERED", "IMAX",
       "DTS", "AC3", "EAC3", "DDP", "DDP5", "ATMOS", "AAC", "TRUEHD", "10BIT", "NF", "AMZN", "DSNP",
       "ATVP", "HMAX", "FLAC", "MP3", "EPUB", "PDF"}
)


def _tokens(title: str) -> list[str]:
    # WEB-DL → WEBDL avant découpage
    title = re.sub(r"(?i)web[\s._-]?dl", "WEBDL", title)
    title = re.sub(r"(?i)hdr10\+", "HDR10PLUS", title)
    title = re.sub(r"(?i)dolby[\s._-]?vision", "DOLBYVISION", title)
    return [t for t in _SPLIT_RE.split(title) if t]


def release_info(title: str, content_type: str = "other") -> dict[str, Any]:
    """Qualité, langue, source… et clé de regroupement."""
    toks = _tokens(title)
    upper = [t.upper() for t in toks]
    tokset = set(upper)

    quality = next((QUALITY_TOKENS[t] for t in upper if t in QUALITY_TOKENS), "sd")
    sources = {SOURCE_TOKENS[t] for t in upper if t in SOURCE_TOKENS}
    source = next((src for src in SOURCE_PRIORITY if src in sources), None)
    codec = next((CODEC_TOKENS[t] for t in upper if t in CODEC_TOKENS), None)
    hdr = sorted({HDR_TOKENS[t] for t in upper if t in HDR_TOKENS})
    if tokset & VF_TOKENS:
        languages = "vf"
    elif tokset & VOSTFR_TOKENS:
        languages = "vostfr"
    else:
        languages = "vo"

    info: dict[str, Any] = {
        "quality": quality,
        "languages": languages,
        "multi": "MULTI" in tokset,
        "source": source,
        "codec": codec,
        "hdr": hdr,
        "proper": bool(tokset & {"PROPER", "REPACK"}),
        "kind": "other",
        "name": None,
        "year": None,
        "season": None,
        "episodes": [],
    }

    episode = parse_release(title)
    if episode is not None:
        info.update(
            kind="pack" if episode.is_pack else "episode",
            name=episode.name,
            year=episode.year,
            season=episode.season,
            episodes=episode.episodes,
        )
        eps = "-".join(f"{e:02d}" for e in episode.episodes) or "pack"
        info["group"] = f"tv|{episode.name}|{episode.year or ''}|{episode.season:02d}|{eps}"
        return info

    # Film / autre : le nom s'arrête au premier mot technique ; l'année est la dernière avant lui.
    stop = next((i for i, t in enumerate(upper) if t in STOP_TOKENS and i > 0), len(toks))
    head = toks[:stop]
    year_idx = max((i for i, t in enumerate(head) if i > 0 and _YEAR_RE.match(t)), default=None)
    if year_idx is not None:
        info["year"] = int(head[year_idx])
        head = head[:year_idx]
    name = normalize(" ".join(head)) or normalize(title)
    info["name"] = name
    if content_type == "movies" or (content_type in ("other", "anime") and info["year"]):
        info["kind"] = "movie"
    info["group"] = f"{info['kind']}|{name}|{info['year'] or ''}"
    return info
