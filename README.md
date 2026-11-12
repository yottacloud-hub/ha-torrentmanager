# C411 + qBittorrent pour Home Assistant

Intégration personnalisée qui affiche le contenu de **C411** directement dans Home Assistant et envoie vos choix à **qBittorrent** en un clic.

- **Panneau « C411 »** dans la barre latérale avec trois onglets :
  - **Nouveautés** : derniers ajouts, filtrables par catégorie (Films, Séries, Animation…) et triables par date, sources, taille ou popularité.
  - **Recherche** : recherche plein texte sur C411, avec filtres et bouton « Afficher plus ».
  - **Téléchargements** : progression en direct, vitesse, temps restant, pause / reprise / revérification / suppression (avec ou sans fichiers).
- Les releases déjà présentes dans qBittorrent sont reconnues grâce à leur infohash et affichent leur progression à la place du bouton « Télécharger ».
- Les torrents envoyés reçoivent l'étiquette `c411` et peuvent être rangés dans une catégorie qBittorrent choisie au moment de l'envoi.
- Le panneau suit le thème de Home Assistant (clair ou sombre) et s'adapte au mobile.
- Des **capteurs**, des **services** et des **événements** permettent d'écrire vos propres automatisations.

## Installation

### Avec HACS
1. HACS → menu ⋮ → **Dépôts personnalisés** → ajoutez `https://github.com/yottacloud-hub/ha-torrentmanager` (type : *Intégration*).

   [![Ouvrir dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=yottacloud-hub&repository=ha-torrentmanager&category=integration)
2. Installez « C411 + qBittorrent », puis redémarrez Home Assistant.

### À la main
1. Copiez le dossier `custom_components/c411` dans le dossier `config/custom_components/` de Home Assistant.
2. Redémarrez Home Assistant.

## Configuration

1. Sur C411, ouvrez **Mon compte → Intégrations API** (`https://c411.org/user/integrations`) et générez une clé API.
2. Dans qBittorrent, activez l'interface web : **Outils → Options → Interface web**. Notez l'adresse (par exemple `http://192.168.1.20:8080`), l'utilisateur et le mot de passe.
3. Dans Home Assistant : **Paramètres → Appareils et services → Ajouter une intégration → C411**.
   - Étape 1 : adresse du site (`https://c411.org` par défaut) et clé API.
   - Étape 2 : URL, utilisateur et mot de passe de qBittorrent.
4. Le panneau **C411** apparaît dans la barre latérale (visible uniquement par les administrateurs).

**Options** (bouton « Configurer » de l'intégration) :

| Option | Rôle |
|---|---|
| Catégories suivies | Limite les nouveautés à certaines catégories (vide = toutes) |
| Nombre de nouveautés | De 10 à 100 |
| Fréquence des nouveautés | 30 min par défaut, 5 min minimum |
| Catégorie qBittorrent par défaut | Pré-sélectionnée dans le panneau |
| Dossier de destination | Vide = dossier par défaut de qBittorrent |
| Étiquette | `c411` par défaut ; sert à repérer les torrents envoyés |
| Ajouter en pause | Pour valider avant de lancer |
| Fréquence qBittorrent | 10 s par défaut ; le panneau ouvert actualise toutes les 4 s |

> **Limite C411** : l'API accepte environ 15 requêtes par minute. L'intégration espace automatiquement ses appels (environ 4 s entre deux requêtes). Une recherche peut donc mettre quelques secondes à répondre si vous enchaînez les clics.

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

Les noms exacts des entités peuvent varier selon la langue de votre installation : vérifiez-les dans **Paramètres → Entités**.

## Services

- `c411.search` : renvoie les résultats (à utiliser avec `response_variable`).
- `c411.download` : envoie un `download_url` à qBittorrent (paramètres facultatifs : `category`, `save_path`, `paused`).
- `c411.refresh` : rafraîchit immédiatement les nouveautés et l'état de qBittorrent.

## Événements

- `c411_download_added` : un torrent vient d'être envoyé à qBittorrent.
- `c411_download_completed` : un torrent vient de terminer (`name`, `size`, `save_path`, `from_c411`).
- `c411_new_releases` : de nouvelles releases sont apparues dans le flux suivi (`count`, `releases`).

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

- **« Impossible de joindre qBittorrent »** : vérifiez que l'URL est joignable depuis la machine Home Assistant. Avec Docker, `localhost` désigne le conteneur lui-même, pas l'hôte.
- **« Identifiants incorrects » alors qu'ils sont bons** : qBittorrent bannit temporairement l'adresse IP après plusieurs échecs de connexion. Attendez, ou ajoutez l'IP de Home Assistant à la liste blanche (Options → Interface web → « Contourner l'authentification pour les clients du sous-réseau »).
- **Clé C411 révoquée** : Home Assistant affiche une demande de réauthentification ; saisissez la nouvelle clé.
- **Le panneau ne se met pas à jour après une mise à jour de l'intégration** : videz le cache du navigateur (Ctrl + F5).

## Sécurité

- Le panneau, les commandes websocket et les services sont réservés aux administrateurs.
- L'intégration ne télécharge que des liens qui pointent vers le domaine C411 configuré : elle ne peut pas servir à récupérer des fichiers depuis d'autres sites.
- La clé API et le mot de passe qBittorrent sont stockés dans la configuration de Home Assistant, comme pour toute autre intégration.

Respectez le règlement de C411 (ratio, durée de partage) ainsi que la législation de votre pays sur le droit d'auteur.

## Développement

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```
Les tests démarrent un vrai Home Assistant avec de faux serveurs C411 et qBittorrent (`tests/fakes.py`).
