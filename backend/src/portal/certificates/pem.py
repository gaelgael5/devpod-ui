"""Normalisation des blocs PEM importés (clés privées, certs, CA).

Un PEM collé depuis Windows arrive en CRLF, souvent sans newline final — OpenSSH
le rejette (`error in libcrypto`), OpenSSL est plus tolérant mais pas toujours.
À appliquer au stockage (import/association) ET à la matérialisation sur disque
(les entrées déjà stockées sales sont ainsi réparées sans migration).
"""

from __future__ import annotations


def normalize_pem(pem: str) -> str:
    """LF uniquement, sans blanc autour, exactement un newline final ('' reste '')."""
    cleaned = pem.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{cleaned}\n" if cleaned else ""
