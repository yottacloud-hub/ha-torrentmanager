"""Constantes de l'intégration C411."""

from __future__ import annotations

DOMAIN = "c411"

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
