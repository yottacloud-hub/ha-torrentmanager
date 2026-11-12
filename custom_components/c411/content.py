"""Détermine le type de contenu d'une release à partir de ses catégories C411."""

from __future__ import annotations

from collections.abc import Iterable

# Catégories précises qui priment sur la règle « premier chiffre »
_SPECIFIC = {
    "5070": "anime",  # Séries d'animation
    "2060": "movies",  # Films d'animation : rangés avec les films
    "3030": "books",  # Livres audio
}
_BY_FAMILY = {
    "1": "games",
    "2": "movies",
    "3": "music",
    "4": "software",
    "5": "series",
    "7": "books",
}


def content_type(categories: Iterable[str] | None) -> str:
    """Renvoie l'un des types de CONTENT_TYPES."""
    cats = [str(c) for c in categories or [] if c]
    for cat in cats:
        if cat in _SPECIFIC:
            return _SPECIFIC[cat]
    for cat in cats:
        if found := _BY_FAMILY.get(cat[:1]):
            return found
    return "other"


def resolve_destination(
    options: dict,
    ctype: str,
    *,
    category: str | None = None,
    save_path: str | None = None,
) -> tuple[str | None, str | None]:
    """Catégorie et dossier qBittorrent à utiliser.

    Priorité : valeur explicite > réglage du type > réglage par défaut.
    Une catégorie explicite vide ("") signifie « aucune catégorie ».
    """
    if category is None:
        category = options.get(f"cat_{ctype}") or options.get("qb_category") or None
    if save_path is None:
        save_path = options.get(f"path_{ctype}") or options.get("qb_save_path") or None
    return (category or None), (save_path or None)
