"""Constantes de l'intégration C411."""

from __future__ import annotations

DOMAIN = "c411"  # identifiant technique conservé (changer casserait les installations existantes)
APP_NAME = "TorrentManager"

# --- Données du config entry -------------------------------------------------
CONF_C411_URL = "c411_url"
CONF_API_KEY = "api_key"
CONF_QB_URL = "qb_url"
CONF_QB_USERNAME = "qb_username"
CONF_QB_PASSWORD = "qb_password"
CONF_QB_VERIFY_SSL = "qb_verify_ssl"

# --- Options -----------------------------------------------------------------
CONF_FEED_CATEGORIES = "feed_categories"
CONF_FEED_LIMIT = "feed_limit"
CONF_FEED_INTERVAL = "feed_interval"  # minutes
CONF_QB_INTERVAL = "qb_interval"  # secondes
CONF_QB_CATEGORY = "qb_category"
CONF_QB_SAVE_PATH = "qb_save_path"
CONF_QB_TAG = "qb_tag"
CONF_START_PAUSED = "start_paused"

DEFAULT_C411_URL = "https://c411.org"
DEFAULT_FEED_LIMIT = 50
DEFAULT_FEED_INTERVAL = 30
DEFAULT_QB_INTERVAL = 10
DEFAULT_QB_TAG = "c411"

# C411 limite l'API à ~15 requêtes / minute (cf. définition Jackett).
C411_MIN_REQUEST_INTERVAL = 4.1

# --- Événements --------------------------------------------------------------
EVENT_DOWNLOAD_ADDED = "c411_download_added"
EVENT_DOWNLOAD_COMPLETED = "c411_download_completed"
EVENT_NEW_RELEASES = "c411_new_releases"

# --- Panneau -----------------------------------------------------------------
PANEL_URL_PATH = "c411"
PANEL_COMPONENT = "c411-panel"
STATIC_URL = "/c411_static"

# Catégories Torznab exposées par C411 (https://c411.org/api/torznab?t=caps)
CATEGORIES: dict[str, str] = {
    "1000": "Jeux vidéo",
    "1030": "Jeux Nintendo",
    "1040": "Jeux Microsoft",
    "1080": "Jeux Sony",
    "1090": "Jeux autres / ROM",
    "2000": "Films & vidéos",
    "2010": "Films collection",
    "2030": "Films étrangers",
    "2050": "Vidéo-clips",
    "2060": "Films d'animation",
    "2070": "Documentaires",
    "2080": "Spectacles",
    "2090": "Concerts",
    "3000": "Audio",
    "3010": "Musique",
    "3030": "Livres audio",
    "3050": "Karaoké / podcasts",
    "4000": "Applications",
    "4030": "Linux & macOS",
    "4040": "Formations",
    "4050": "Logiciels divers",
    "4060": "Android",
    "4070": "iOS",
    "5000": "Séries TV",
    "5060": "Sport",
    "5070": "Séries d'animation",
    "5080": "Émissions TV",
    "6000": "Adulte",
    "7000": "Ebooks",
    "7010": "Presse",
    "7020": "Livres",
    "7030": "BD / Comics / Manga",
    "8010": "Impression 3D",
}

# Catégories « parentes » proposées dans les filtres
TOP_CATEGORIES: dict[str, str] = {
    "2000": "Films",
    "5000": "Séries",
    "5070": "Animation",
    "5080": "Émissions",
    "3000": "Audio",
    "7000": "Ebooks",
    "1000": "Jeux",
    "4000": "Logiciels",
}

# --- Types de contenu (dossiers / catégories qBittorrent par type) -------------
CONTENT_TYPES: dict[str, str] = {
    "movies": "Films",
    "series": "Séries",
    "anime": "Animation (séries)",
    "music": "Musique & audio",
    "books": "Livres, BD & presse",
    "games": "Jeux",
    "software": "Logiciels",
    "other": "Autre",
}
CONF_PATH_PREFIX = "path_"
CONF_CAT_PREFIX = "cat_"

# --- Plex & suivi des séries ---------------------------------------------------
CONF_PLEX_URL = "plex_url"
CONF_PLEX_TOKEN = "plex_token"
CONF_PLEX_VERIFY_SSL = "plex_verify_ssl"
CONF_PLEX_SECTIONS = "plex_sections"
CONF_PLEX_INTERVAL = "plex_interval"  # minutes
CONF_PLEX_REFRESH_ON_COMPLETE = "plex_refresh_on_complete"
CONF_SERIES_ENABLED = "series_enabled"
CONF_SERIES_AUTO = "series_auto"
CONF_SERIES_FOLLOW_NEW = "series_follow_new"
CONF_SERIES_INTERVAL = "series_interval"  # minutes
CONF_SERIES_QUALITY = "series_quality"
CONF_SERIES_QUALITIES = "series_qualities"
CONF_SERIES_LANGUAGES = "series_languages"
CONF_SERIES_MIN_SEEDERS = "series_min_seeders"
CONF_SERIES_EXCLUDE = "series_exclude"
CONF_SERIES_PACKS = "series_packs"
CONF_SERIES_MAX_GRABS = "series_max_grabs"
CONF_SERIES_NOTIFY = "series_notify"

DEFAULT_PLEX_INTERVAL = 60
DEFAULT_SERIES_INTERVAL = 30
DEFAULT_SERIES_QUALITY = "1080p"
DEFAULT_SERIES_QUALITIES = ["1080p", "720p"]
DEFAULT_SERIES_LANGUAGES = ["vf"]
DEFAULT_SERIES_EXCLUDE = "CAM, HDCAM, TS, HDTS, TELESYNC"
DEFAULT_SERIES_MAX_GRABS = 5

QUALITIES = {"2160p": "4K / 2160p", "1080p": "1080p", "720p": "720p", "sd": "SD (480p…)"}
LANGUAGE_GROUPS = {
    "vf": "VF / MULTi (français inclus)",
    "vostfr": "VOSTFR (sous-titres français)",
    "vo": "VO seule",
}
SERIES_CATEGORIES = ["5000", "5070", "5080"]

EVENT_EPISODE_GRABBED = "c411_episode_grabbed"

# --- Affichage ---------------------------------------------------------------
CONF_HIDE_ADULT = "hide_adult"
CONF_BEST_ONLY = "best_only"
CONF_PREF_QUALITY = "pref_quality"
CONF_PREF_LANGUAGE = "pref_language"
CONF_TMDB_KEY = "tmdb_api_key"
DEFAULT_PREF_QUALITY = "1080p"
DEFAULT_PREF_LANGUAGE = "vf"

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w185"

# --- Accès des utilisateurs non administrateurs -------------------------------
CONF_USER_ACCESS = "user_access"
ACCESS_LEVELS = {
    "admins": "Administrateurs uniquement",
    "view": "Consultation seule",
    "download": "Consultation et téléchargement",
    "full": "Accès complet (suppression, réglages des séries)",
}
DEFAULT_USER_ACCESS = "download"
