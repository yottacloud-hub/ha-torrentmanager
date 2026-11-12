# Journal des modifications

Les versions suivent [SemVer](https://semver.org/lang/fr/) : `MAJEUR.MINEUR.CORRECTIF`.
Pour publier une version : augmenter `version` dans `custom_components/c411/manifest.json`,
ajouter sa section ci-dessous, puis fusionner sur `main`. La release GitHub est créée automatiquement.

## [1.2.0] - 2026-11-12

### Ajouté
- **Meilleure version seulement** : les différentes releases d'un même film ou épisode sont regroupées ;
  seule la mieux notée s'affiche, avec un lien « +N versions » pour voir les autres.
  La note tient compte de la qualité et de la langue préférées, puis de la réputation
  (sources, téléchargements complétés, freeleech, source BluRay/WEB, PROPER).
- **Filtres rapides** dans Nouveautés et Recherche : qualité (Toutes, 4K, 1080p, 720p), langue (Toutes, VF/MULTi, VOSTFR).
  Ils sont mémorisés par navigateur.
- Étiquettes de version lisibles : qualité, langue, source, codec, HDR / Dolby Vision.
- **Affiches** : via TMDB (clé API gratuite, facultative), avec titre français, année et note.
  Les épisodes de vos séries Plex utilisent l'affiche Plex.
- **Contenu adulte masqué** par défaut (option).
- **Accès des utilisateurs non administrateurs** : administrateurs uniquement, consultation seule,
  consultation et téléchargement (par défaut), ou accès complet.
- Nouvel écran d'options « Affichage et accès ».

### Modifié
- L'application s'appelle désormais **TorrentManager** (barre latérale, panneau, intégration, HACS).
  L'identifiant technique `c411` est conservé : rien à reconfigurer.

## [1.1.0] - 2026-11-12

### Ajouté
- **Plex** : connexion à votre serveur (options → « Connexion Plex »).
- **Suivi des séries** : nouvel onglet « Séries » avec les affiches de votre bibliothèque Plex, le dernier épisode possédé
  et les nouveaux épisodes trouvés sur C411.
  - Téléchargement automatique des épisodes qui suivent le dernier épisode présent dans Plex, série par série (interrupteurs « Suivre » et « Auto »).
  - Règles : qualité préférée et acceptées, langues (VF/MULTi, VOSTFR, VO), sources minimum, mots exclus, packs de saison.
  - Plex est rescanné automatiquement quand un téléchargement C411 se termine.
  - Notification Home Assistant, événement `c411_episode_grabbed`, service `c411.check_series`,
    capteurs « Séries suivies » et « Nouveaux épisodes disponibles ».
- **Dossiers par type** : un dossier et une catégorie qBittorrent pour chaque type de contenu
  (films, séries, animation, musique, livres, jeux, logiciels, autre). Dans le panneau, la destination
  « Automatique (selon le type) » est sélectionnée par défaut et s'affiche au survol du bouton « Télécharger ».
- Options réorganisées en menu : Général, Dossiers par type, Connexion Plex, Suivi des séries.
- Releases GitHub automatiques à chaque nouvelle version.

## [1.0.0] - 2026-11-12

### Ajouté
- Panneau « C411 » : nouveautés, recherche, téléchargements qBittorrent (pause, reprise, suppression).
- Envoi des torrents C411 vers qBittorrent avec étiquette `c411`.
- Capteurs, services `c411.search` / `c411.download` / `c411.refresh`, événements.
