# TorrentManager pour Home Assistant

**TorrentManager** est une intégration personnalisée qui affiche le contenu de **C411** directement dans Home Assistant, envoie vos choix à **qBittorrent** en un clic, et suit vos séries **Plex** pour récupérer les nouveaux épisodes dès leur sortie.

- **Panneau « TorrentManager »** dans la barre latérale avec cinq onglets :
  - **Nouveautés** : derniers ajouts, filtrables par catégorie (Films, Séries, Animation…) et triables par date, sources, taille ou popularité.
  - **Recherche** : recherche plein texte sur C411, avec filtres et bouton « Afficher plus ».
  - **Pour vous** : recommandations du catalogue Plex d'après vos téléchargements et vos séries suivies, et ce qui est populaire en ce moment sur C411.
  - **Séries** : vos séries Plex avec leur affiche, le dernier épisode possédé, les nouveaux épisodes trouvés sur C411 et des interrupteurs « Suivre » / « Auto ».
  - **Téléchargements** : progression en direct, vitesse, temps restant, pause / reprise / revérification / suppression (avec ou sans fichiers).
- **Une seule carte par contenu** : les différentes versions d'un même film ou épisode sont regroupées, et la meilleure s'affiche selon vos préférences de qualité et de langue, puis selon sa réputation. Des filtres rapides (4K, 1080p, 720p ; VF/MULTi, VOSTFR) et un lien « +N versions » permettent de voir le reste.
- **Affiches**, titre français et note pour les films et séries, depuis le catalogue Plex (même jeton que la connexion Plex).
- Contenu pour adultes masqué par défaut.
- Accessible aux utilisateurs non administrateurs, avec le niveau d'accès de votre choix.
- Les releases déjà présentes dans qBittorrent sont reconnues grâce à leur infohash et affichent leur progression à la place du bouton « Télécharger ».
- Les torrents envoyés reçoivent l'étiquette `c411` et sont rangés **dans le dossier et la catégorie de leur type** (films, séries, musique…).
- Le panneau suit le thème de Home Assistant (clair ou sombre) et s'adapte au mobile.
- Des **capteurs**, des **services** et des **événements** permettent d'écrire vos propres automatisations.

## Installation

### Avec HACS
1. HACS → menu ⋮ → **Dépôts personnalisés** → ajoutez `https://github.com/yottacloud-hub/ha-torrentmanager` (type : *Intégration*).

   [![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yottacloud-hub&repository=ha-torrentmanager&category=integration)
2. Installez « TorrentManager », puis redémarrez Home Assistant.

### À la main
1. Copiez le dossier `custom_components/c411` dans le dossier `config/custom_components/` de Home Assistant.
2. Redémarrez Home Assistant.

## Configuration

1. Sur C411, ouvrez **Mon compte → Intégrations API** (`https://c411.org/user/integrations`) et générez une clé API.
2. Dans qBittorrent, activez l'interface web : **Outils → Options → Interface web**. Notez l'adresse (par exemple `http://192.168.1.20:8080`), l'utilisateur et le mot de passe.
3. Dans Home Assistant : **Paramètres → Appareils et services → Ajouter une intégration → C411**.
   - Étape 1 : adresse du site (`https://c411.org` par défaut) et clé API.
   - Étape 2 : URL, utilisateur et mot de passe de qBittorrent.
4. Le panneau **TorrentManager** apparaît dans la barre latérale.

**Options** (bouton « Configurer » de l'intégration) : un menu à cinq entrées.

**Général**

| Option | Rôle |
|---|---|
| Catégories suivies | Limite l'onglet Nouveautés à certaines catégories (vide = toutes) |
| Nombre et fréquence des nouveautés | 50 releases toutes les 30 min par défaut |
| Catégorie / dossier par défaut | Utilisés quand rien n'est réglé pour le type |
| Étiquette | `c411` par défaut ; sert à repérer les torrents envoyés |
| Ajouter en pause | Pour valider avant de lancer |
| Fréquence qBittorrent | 10 s par défaut ; le panneau ouvert actualise toutes les 4 s |

**Affichage et accès**

| Option | Par défaut |
|---|---|
| Masquer le contenu pour adultes | Activé |
| Meilleure version seulement | Activé (modifiable aussi dans le panneau) |
| Qualité / langue préférées pour choisir la meilleure version | 1080p / VF |
| Clé API TMDB | Vide, et inutile si Plex est connecté : les affiches et recommandations viennent du catalogue Plex. TMDB ne sert qu'en complément ou sans Plex |
| Accès des utilisateurs non administrateurs | Consultation et téléchargement |

Niveaux d'accès pour les comptes non administrateurs (les administrateurs ont toujours tous les droits) :

| Niveau | Voir | Télécharger, pause / reprise, vérifier les séries | Supprimer des torrents, régler le suivi des séries |
|---|---|---|---|
| Administrateurs uniquement | — (panneau masqué) | — | — |
| Consultation seule | ✓ | — | — |
| Consultation et téléchargement | ✓ | ✓ | — |
| Accès complet | ✓ | ✓ | ✓ |

Comment est choisie la meilleure version : la qualité la plus proche de la qualité préférée, puis la langue préférée (MULTi en bonus), puis la réputation : nombre de sources, téléchargements complétés, freeleech, source (REMUX > BluRay > WEB-DL > WEBRip…). Les versions sans aucune source et les CAM sont fortement pénalisées.

**Dossiers par type** : pour chaque type de contenu, un dossier (tel que qBittorrent le voit, ex. `/data/series`) et une catégorie qBittorrent.

| Type | Catégories C411 |
|---|---|
| Films | Films & vidéos, y compris films d'animation, documentaires, concerts |
| Séries | Séries TV, émissions, sport |
| Animation (séries) | Séries d'animation |
| Musique & audio | Musique, karaoké, podcasts |
| Livres, BD & presse | Ebooks, presse, BD/mangas, livres audio |
| Jeux / Logiciels / Autre | Le reste |

Dans le panneau, la destination « Automatique (selon le type) » est choisie par défaut ; survolez « Télécharger » pour voir où ira le fichier. Vous pouvez forcer une autre catégorie au cas par cas.

**Connexion Plex** : adresse du serveur (ex. `http://192.168.1.20:32400`) et jeton `X-Plex-Token`. Pour trouver le jeton : dans Plex Web, ouvrez un épisode → ⋯ → **Obtenir des infos** → **Afficher le XML** ; il figure à la fin de l'adresse qui s'ouvre. Option : rescanner Plex quand un téléchargement C411 se termine (activé par défaut).

**Suivi des séries** (disponible une fois Plex connecté)

| Option | Par défaut |
|---|---|
| Téléchargement automatique | Activé |
| Suivre les nouvelles séries de Plex | Activé |
| Bibliothèques suivies | Toutes les bibliothèques de séries |
| Qualité préférée / acceptées | 1080p / 1080p et 720p |
| Langues acceptées | VF / MULTi |
| Sources minimum | 1 |
| Mots exclus | `CAM, HDCAM, TS, HDTS, TELESYNC` |
| Packs de saison | Acceptés pour une saison entièrement absente de Plex |
| Téléchargements auto max. par vérification | 5 (garde-fou) |
| Vérification C411 / relecture Plex | 30 min / 60 min |
| Rattraper toutes les saisons suivantes manquantes | Activé |
| Notifications (nouvelle saison, épisode envoyé) | Activées |
| Service de notification du téléphone | Aucun (ex. `notify.mobile_app_mon_telephone`) |

> **Limite C411** : l'API accepte environ 15 requêtes par minute. L'intégration espace automatiquement ses appels (environ 4 s entre deux requêtes). Une recherche peut donc mettre quelques secondes à répondre si vous enchaînez les clics.

## Suivi des séries : comment ça marche

1. L'intégration relit votre bibliothèque Plex et note, pour chaque série, le **dernier épisode présent**.
2. Toutes les 30 min, elle lit les dernières séries publiées sur C411 et fait aussi une recherche ciblée sur deux séries suivies, à tour de rôle (la limite de 15 requêtes par minute de C411 est respectée).
3. Une release est retenue si elle correspond à la série (identifiant TMDb/IMDb, sinon nom et année), si l'épisode vient **après** le dernier présent dans Plex, et si elle respecte vos règles. À épisode égal, la meilleure release gagne : qualité préférée, langue, MULTi, PROPER/REPACK, nombre de sources.
4. Si la série est suivie avec « Auto », l'épisode part dans qBittorrent, dans le dossier « Séries » (ou « Animation »). Il est mémorisé comme récupéré et n'est plus téléchargé une seconde fois.
5. Quand le téléchargement se termine, Plex est rescanné ; l'épisode apparaît dans Plex et devient le nouveau « dernier épisode ».

**Saisons suivantes** : si vous n'avez que la saison 1, les saisons 2, 3… sont recherchées (par nom, par identifiant de la série, puis saison par saison) et téléchargées, en privilégiant les packs de saison complets. À chaque nouvelle saison trouvée, vous recevez **une** notification (« téléchargement lancé » ou « à télécharger »), dans Home Assistant et, si vous le choisissez dans les options, sur votre téléphone (`notify.mobile_app_…`). L'option « Rattraper toutes les saisons suivantes manquantes » peut être désactivée pour ne prendre que la saison en cours et la suivante.

Les épisodes manquants **avant** le dernier épisode possédé ne sont pas recherchés : c'est voulu, pour ne pas retélécharger ce que vous avez supprimé exprès. Le bouton ↺ à côté d'un épisode récupéré permet de l'oublier pour le retélécharger.

Si une série a pris du retard (par exemple vous avez la saison 2 et la saison 4 est en cours), le rattrapage se fait progressivement, au plus 5 téléchargements automatiques par vérification par défaut.

## Capteurs

| Entité | Contenu |
|---|---|
| `sensor.c411_derniere_nouveaute` | Titre de la dernière release ; l'attribut `releases` contient les 10 dernières |
| `sensor.qbittorrent_vitesse_de_telechargement` | Vitesse globale de réception (Mo/s) |
| `sensor.qbittorrent_vitesse_d_envoi` | Vitesse globale d'envoi (Mo/s) |
| `sensor.qbittorrent_telechargements_actifs` | Nombre de téléchargements en cours |
| `sensor.qbittorrent_telechargements_c411_actifs` | Idem, limité aux torrents venus de C411 |
| `sensor.qbittorrent_torrents` | Nombre total de torrents |
| `sensor.qbittorrent_torrents_c411` | Nombre de torrents C411 ; l'attribut `torrents` donne leur progression |
| `sensor.plex_suivi_des_series_series_suivies` | Nombre de séries suivies |
| `sensor.plex_suivi_des_series_nouveaux_episodes_disponibles` | Épisodes trouvés et pas encore téléchargés ; l'attribut `episodes` les détaille |

Les noms exacts des entités peuvent varier selon la langue de votre installation : vérifiez-les dans **Paramètres → Entités**.

## Services

- `c411.search` : renvoie les résultats (à utiliser avec `response_variable`).
- `c411.download` : envoie un `download_url` à qBittorrent. Paramètres facultatifs : `type` ou `categories` (pour choisir le dossier du type), `category`, `save_path`, `paused`.
- `c411.check_series` : lance tout de suite la recherche de nouveaux épisodes ; renvoie la liste trouvée.
- `c411.refresh` : rafraîchit immédiatement les nouveautés et l'état de qBittorrent.

## Événements

- `c411_download_added` : un torrent vient d'être envoyé à qBittorrent.
- `c411_download_completed` : un torrent vient de terminer (`name`, `size`, `save_path`, `from_c411`).
- `c411_new_releases` : de nouvelles releases sont apparues dans le flux suivi (`count`, `releases`).
- `c411_episode_grabbed` : un épisode a été envoyé à qBittorrent (`show`, `episode`, `title`, `automatic`).
- `c411_new_season` : une nouvelle saison d'une série suivie est disponible (`show`, `season`, `downloading`).

## Exemples

### Notification à la fin d'un téléchargement
```yaml
automation:
  - alias: "C411 – téléchargement terminé"
    triggers:
      - trigger: event
        event_type: c411_download_completed
        event_data:
          from_c411: true
    actions:
      - action: notify.mobile_app_mon_telephone
        data:
          title: "Téléchargement terminé"
          message: "{{ trigger.event.data.name }}"
```

### Télécharger automatiquement le meilleur résultat d'une recherche
```yaml
script:
  c411_telecharger_meilleur:
    fields:
      recherche: { example: "Shogun S02E04 1080p" }
    sequence:
      - action: c411.search
        data: { query: "{{ recherche }}", limit: 20 }
        response_variable: r
      - condition: template
        value_template: "{{ r.results | count > 0 }}"
      - action: c411.download
        data:
          url: "{{ (r.results | sort(attribute='seeders', reverse=true) | first).download_url }}"
          title: "{{ (r.results | sort(attribute='seeders', reverse=true) | first).title }}"
          category: series
```

### Carte de tableau de bord (progression des téléchargements C411)
```yaml
type: markdown
title: Téléchargements C411
content: >
  {% for t in state_attr('sensor.qbittorrent_torrents_c411', 'torrents') or [] %}
  **{{ t.name }}** — {{ t.progress }} % · {{ (t.dlspeed / 1048576) | round(1) }} Mo/s
  {% else %}
  Aucun téléchargement.
  {% endfor %}
```

## Dépannage

- **« qBittorrent : fichier torrent invalide »** (avant la 1.3.0) : mettez à jour. TorrentManager vérifie désormais le fichier et, s'il le faut, confie le lien à qBittorrent. Si une erreur persiste, le journal de Home Assistant (Paramètres → Système → Journaux, filtre `c411`) indique ce que C411 a renvoyé.
- **Pas d'affiches** : connectez Plex (Configurer → Connexion Plex). Le même jeton donne accès au catalogue en ligne de Plex. Si rien ne s'affiche malgré tout, le journal (filtre `c411`) indique la réponse du catalogue.

- **« Impossible de joindre qBittorrent »** : vérifiez que l'URL est joignable depuis la machine Home Assistant. Avec Docker, `localhost` désigne le conteneur lui-même, pas l'hôte.
- **« Identifiants incorrects » alors qu'ils sont bons** : qBittorrent bannit temporairement l'adresse IP après plusieurs échecs de connexion. Attendez, ou ajoutez l'IP de Home Assistant à la liste blanche (Options → Interface web → « Contourner l'authentification pour les clients du sous-réseau »).
- **Clé C411 révoquée** : Home Assistant affiche une demande de réauthentification ; saisissez la nouvelle clé.
- **Le panneau ne se met pas à jour après une mise à jour de l'intégration** : videz le cache du navigateur (Ctrl + F5).

## Sécurité

- Le panneau et ses commandes respectent le niveau d'accès choisi pour les comptes non administrateurs. Les services Home Assistant (`c411.*`) suivent les règles habituelles de Home Assistant.
- L'intégration ne télécharge que des liens qui pointent vers le domaine C411 configuré : elle ne peut pas servir à récupérer des fichiers depuis d'autres sites.
- La clé API et le mot de passe qBittorrent sont stockés dans la configuration de Home Assistant, comme pour toute autre intégration.

Respectez le règlement de C411 (ratio, durée de partage) ainsi que la législation de votre pays sur le droit d'auteur.

## Versions

Chaque version est publiée comme release GitHub : HACS vous propose alors la mise à jour. La liste des changements est dans [CHANGELOG.md](CHANGELOG.md).

Pour publier une version : augmenter `version` dans `custom_components/c411/manifest.json`, ajouter la section correspondante dans `CHANGELOG.md`, puis fusionner sur `main`. Le workflow **Release** crée l'étiquette `vX.Y.Z`, la release et l'archive `c411.zip`. La CI refuse une version absente du CHANGELOG.

## Développement

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
# version de home-assistant-frontend : voir homeassistant/components/frontend/manifest.json
pip install home-assistant-frontend==<version>
pytest
```
Les tests démarrent un vrai Home Assistant avec de faux serveurs C411 et qBittorrent (`tests/fakes.py`).
