# Journal des modifications

Les versions suivent [SemVer](https://semver.org/lang/fr/) : `MAJEUR.MINEUR.CORRECTIF`.
Pour publier une version : augmenter `version` dans `custom_components/c411/manifest.json`,
ajouter sa section ci-dessous, puis fusionner sur `main`. La release GitHub est créée automatiquement.

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
