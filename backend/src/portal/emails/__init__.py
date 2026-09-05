"""Emails du cycle d'abonnement, via Listmonk (fiche 6fdfdaab).

Décidé sur la fiche : email uniquement, pas de notification in-app. Le
vocabulaire tient les distinctions que le code tient déjà — arrêté n'est pas
supprimé, résilié n'est pas compte fermé.

Découpage :

- `formatage`   : dates, montants, périodicité — localisés CÔTÉ PORTAIL, les
                  templates sont bêtes ;
- `templates`   : les 12 templates transactionnels (6 messages × fr/en),
                  source de vérité versionnée, poussée vers Listmonk par
                  l'action admin « sync » (jamais au démarrage) ;
- `listmonk_tx` : le client `POST /api/tx` + gestion des templates ;
- `service`     : composition du payload, journal d'envoi (dédup par épisode,
                  payload figé — pour prouver ce qui a été annoncé), envois.
"""
