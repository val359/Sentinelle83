# Sentinelle83

Surveillance d'informations liées aux incendies autour de Fréjus.

## Installation

```bash
./install.sh
source .venv/bin/activate
python main.py --test-alert
python main.py --once
python main.py
```

Arrêt : `Ctrl+C`.

## Voir les résultats déjà publiés

```bash
python main.py --reset
python main.py --once --show-existing
```

## Démarrage automatique

```bash
./install_service.sh
systemctl --user status sentinelle83
```

## Telegram

Renseigner `bot_token` et `chat_id` dans `config.json`.

Facebook est désactivé par défaut car l'accès automatisé est instable. Il peut être activé dans `config.json`, mais ce n'est qu'une source complémentaire.

Ce programme ne remplace pas FR-Alert, la préfecture, le 18 ou le 112.
