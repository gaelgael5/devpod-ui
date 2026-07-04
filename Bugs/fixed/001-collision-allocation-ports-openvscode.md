# 001 — Collision d'allocation de ports openvscode entre workspaces

- **Sévérité** : majeur
- **Sous-système** : devpod / exposure
- **Fichiers** :
  - `backend/src/portal/exposure/ports.py` (`PortRegistry.allocate`, `_used_ports`)
  - `backend/src/portal/devpod/service.py` (`_write_status(ws_id, "provisioning")`, `reconcile_port_forwards`)
- **Statut** : ✅ corrigé

## Symptôme

Deux workspaces différents peuvent se voir attribuer le **même** `host_port` (ex. 40000).
Le tunnel SSH du second bind un port déjà occupé ou pointe vers le mauvais conteneur ;
le proxy VS Code sert alors un workspace pour un autre, ou le tunnel meurt.
Observé en production sur dev.yoops.org : `admin-rag` et `admin-devpod` tous deux persistés
avec `host_port=40000` après des redémarrages en rafale.

## Scénario de déclenchement

1. `PortRegistry` suit les ports pris via deux sources : les `host_port` **persistés en DB**
   (`_used_ports`) + un set mémoire `_reserved` des ports alloués mais pas encore persistés.
2. **Fenêtre 1 — provisioning** : au lancement d'un workspace, `_write_status(ws_id, "provisioning")`
   écrit un statut **sans `host_port`** → la colonne repasse à NULL pendant toute la durée du
   `devpod up` (jusqu'à 30 min). Pendant cette fenêtre, `_used_ports()` ne voit plus ce port
   comme pris. Seul `_reserved` le protège encore.
3. **Fenêtre 2 — redémarrage** : `_reserved` est un attribut d'instance en mémoire. Il est perdu
   à chaque redémarrage du portail **et** à chaque `_reset_service()` (invalidation du singleton
   `DevPodService` après un `PUT /admin/network`). La réconciliation au démarrage
   (`reconcile_port_forwards`) déclenche des `devpod up` concurrents → plusieurs allocations
   simultanées sans mémoire partagée des réservations.
4. Résultat : deux `allocate()` concurrents (ou un `allocate()` pendant qu'un autre workspace est
   en provisioning avec son port temporairement NULL en DB) renvoient le même numéro.

## Cause racine

L'unicité du port repose sur la conjonction **DB (source durable)** + **`_reserved` (mémoire volatile)**,
mais les deux ont des trous complémentaires :
- la DB ne reflète pas le port pendant le provisioning (`host_port` remis à NULL) ;
- `_reserved` ne survit ni au restart ni au `_reset_service()`.

Il n'existe aucune réservation **durable et atomique** du port au moment de l'allocation.

`backend/src/portal/exposure/ports.py` :
```python
async def allocate(self, ws_id: str) -> int:
    async with self._lock:                 # verrou intra-instance seulement
        db_ports = await self._used_ports() # ne voit pas les workspaces en provisioning
        self._reserved -= db_ports
        used = db_ports | self._reserved    # _reserved volatile
        for port in range(_PORT_MIN, _PORT_MAX + 1):
            if port not in used:
                self._reserved.add(port)
                return port
```

## Piste de correction

Rendre la réservation **durable dès l'allocation**, deux options :

1. **Préférée** — persister le `host_port` en DB **au moment de l'allocation** (statut `provisioning`
   inclus), au lieu de le remettre à NULL. `_write_status("provisioning")` doit préserver le
   `host_port` déjà alloué (le passer en paramètre ou faire un UPDATE partiel qui ne touche pas la
   colonne). `_used_ports()` deviendrait alors la seule source de vérité, `_reserved` ne servant
   plus qu'à couvrir la fenêtre entre `allocate()` et le premier `_write_status`.

2. **Alternative** — réutiliser le port existant d'un workspace lors d'un re-up (reconnexion,
   restart) au lieu d'en réallouer un neuf : si une ligne `workspace_status` existe déjà pour ce
   `ws_id` avec un `host_port`, le reprendre tel quel. Cela supprime la réallocation en rafale au
   démarrage, qui est le déclencheur principal.

Idéalement les deux. Vérifier aussi que `_write_status` n'écrase jamais un `host_port` non-NULL
par NULL sur un chemin de statut intermédiaire.

## Notes

- Depuis le commit `4c7dfdc` (`ExitOnForwardFailure=yes` + kill du tunnel précédent), un conflit
  de bind est au moins **bruyant** (`port_forward_died` dans les logs) au lieu d'un proxy silencieux
  qui sert le mauvais workspace. Mais la cause structurelle de l'allocation dupliquée reste entière.

## Correction (92fc21c)

host_port persisté dès le statut provisioning (plus jamais NULL pendant le up) + réutilisation du port persisté au re-up (fin de la réallocation en rafale à la réconciliation). Tests : harnais status_store + PortRegistry neuf sur ligne provisioning.

**Durcissement (suite au signalement du 2026-07-04, « Open VS Code ouvre toujours rag ») :** le re-up ne réutilise jamais un port qu'un AUTRE workspace revendique aussi (`port_claimed_by_other_db`) — un doublon hérité de l'ancienne allocation (admin-rag et admin-devpod tous deux persistés à 40000) se serait sinon perpétué à chaque reconnexion. Le workspace ré-uppé réalloue et assainit sa ligne ; log `port_duplicate_detected`.
