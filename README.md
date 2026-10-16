# TCAT Troyes pour Home Assistant

Le prochain bus [TCAT](https://www.tcat.fr/) à vos arrêts favoris, avec le retard en temps réel quand le bus est suivi.

Pour chaque arrêt suivi (une ligne, un arrêt, une direction), deux capteurs :

| Capteur | Valeur | Attributs |
|---|---|---|
| `sensor.tcat_3_hoche_ganne_prochain_bus` | heure du prochain bus (horodatage : le tableau de bord affiche « dans 7 minutes ») | `terminus`, `realtime`, `delay` (minutes), `line`, `line_color`, `upcoming` (les bus suivants) |
| `sensor.tcat_3_hoche_ganne_prochain_bus_dans` | minutes avant ce bus | |

Indiquez votre **temps de marche** jusqu'à l'arrêt : les bus que vous ne pouvez plus attraper sont ignorés.
Sans suivi en temps réel (bus pas encore parti, flux indisponible), c'est l'horaire théorique.

## Installation

Avec [HACS](https://hacs.xyz/) : *HACS → ⋮ → Dépôts personnalisés*, ajoutez `https://github.com/Eylexander/ha-tcat`
(type *Intégration*), installez **TCAT Troyes**, puis redémarrez Home Assistant.

Sans HACS : copiez `custom_components/tcat` dans le dossier `config/custom_components/` de Home Assistant, puis redémarrez.

## Configuration

*Paramètres → Appareils et services → Ajouter une intégration → TCAT Troyes* : choisissez la ligne, puis l'arrêt et sa
direction. Ajoutez l'intégration une fois par arrêt à suivre. Le temps de marche se change ensuite dans *Configurer*.

Exemple de carte :

```yaml
type: tile
entity: sensor.tcat_3_hoche_ganne_prochain_bus
```

Ou une notification quand il est temps de partir :

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.tcat_3_hoche_ganne_prochain_bus_dans
    below: 3
actions:
  - action: notify.notify
    data:
      message: "Bus dans {{ states('sensor.tcat_3_hoche_ganne_prochain_bus_dans') }} min"
```

## Sans Home Assistant

`custom_components/tcat/tcat.py` fonctionne seul (Python ≥ 3.11, aucune dépendance ; sous Windows : `pip install tzdata`) :

```sh
python custom_components/tcat/tcat.py                 # les lignes
python custom_components/tcat/tcat.py 3               # les arrêts de la ligne 3
python custom_components/tcat/tcat.py 3 "HOCHE|1" 5   # les prochains bus, en comptant 5 min de marche
```

## Fonctionnement

- Horaires : le GTFS du réseau TCAT sur [transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/donnees-tcat-troyes-champagne-metropole-1),
  retéléchargé toutes les 6 heures (TCAT en publie un nouveau toutes les quelques semaines).
- Temps réel : le flux GTFS-RT *TripUpdates* de TCAT, interrogé toutes les 30 secondes et partagé entre tous les
  arrêts suivis. Un bus annulé, qui ne s'arrête pas à votre arrêt ou qui l'a déjà passé disparaît de la liste.

Données : Troyes Champagne Métropole / TCAT, [Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
Ce projet n'est pas affilié à TCAT.

## Développement

```sh
python tests/test_tcat.py                                     # logique seule, sans Home Assistant
pip install pytest-homeassistant-custom-component && pytest   # tout, dans Home Assistant (Python 3.14)
```

---

*English: a Home Assistant integration for the next buses of TCAT, the Troyes (France) bus network, from its open GTFS
and GTFS-RT feeds. Add it once per favourite stop; each gives a timestamp sensor and a "minutes until" sensor.*
