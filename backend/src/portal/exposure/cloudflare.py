"""
Stub M6 — Modèle wildcard unique retenu (§F-32).

*.dev.yoops.org est routé par Cloudflare Tunnel vers Caddy (posé en M5).
M6 n'appelle pas cloudflare-manager par workspace : toutes les routes workspace
sont gérées dynamiquement par Caddy via son API admin (CaddyClient).

Si un modèle per-hostname est requis en M7 (ex. sous-domaines custom par user),
implémenter ici les méthodes suivantes :
  - async def add_hostname(hostname: str) -> None
  - async def remove_hostname(hostname: str) -> None

Pour l'instant, ce module ne contient aucune classe ni fonction exportée.
"""
