# 013 — SAN de la CSR trop permissif : un nœud peut se faire signer un cert valide pour d'autres nœuds

- **Sévérité** : majeur (usurpation de daemon Docker inter-nœuds, MITM mTLS)
- **Sous-système** : nodes (enrôlement mTLS)
- **Fichier** : `backend/src/portal/nodes/enroll.py` — `_validate_csr` / `_address_in_san` (~62-69), `sign_csr` (~92, 101)
- **Statut** : ouvert

## Symptôme

Un nœud légitime (détenteur d'un join token pour `node-a` / `10.0.0.10`) peut obtenir un certificat
serveur Docker **valide pour l'IP d'un autre nœud** (`10.0.0.20`), et ainsi usurper le daemon Docker
de cet autre nœud — MITM sur le trafic mTLS que le portail dirige vers lui.

## Cause racine

`_validate_csr` vérifie seulement que `expected_address` est **contenu** dans le SAN
(`_address_in_san`), pas qu'il en est le **seul** élément. `sign_csr` recopie ensuite le SAN
**intégral** de la CSR dans le cert signé (`.add_extension(san_ext.value, ...)`) avec
`ExtendedKeyUsage=SERVER_AUTH`. Un nœud peut donc soumettre une CSR dont le SAN contient
`10.0.0.10` **et** `10.0.0.20`, passer la validation, et recevoir un cert couvrant les deux.

## Piste de correction

Ne pas recopier le SAN de la CSR. **Reconstruire** côté portail un SAN autoritatif contenant
uniquement `expected_address` (et éventuellement le `node_name`), au lieu de signer `san_ext.value`
verbatim.

## Vérifié

Rapporté par l'agent d'audit avec les lignes précises ; la logique « contenu dans » + recopie
verbatim du SAN est le cœur du défaut. À confirmer par lecture de `_validate_csr`/`sign_csr` avant
correction.
