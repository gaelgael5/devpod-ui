"""Sonde d'occupation disque des hosts.

Le parsing de `df` est la partie fragile : format variable selon l'implémentation,
noms de device longs qui font passer la ligne à la ligne, réserve root qui fausse
la colonne `Capacity`. Un mauvais parsing donne une alerte fantôme — ou pire, un
silence sur un disque plein (incident du 17/08 : host-dev-01 à 100 %, zéro alerte).
"""

from __future__ import annotations

from portal.nodes.disk import parse_df

# Sortie type de `df -PB1 /var/lib/docker` (octets bruts, format POSIX).
REAL = """Filesystem       1B-blocks         Used    Available Capacity Mounted on
/dev/sda1      46036664320  44038193152            0     100% /
"""


def test_parses_real_output() -> None:
    parsed = parse_df(REAL)
    assert parsed is not None
    total, used, avail, pct = parsed
    assert total == 46036664320
    assert used == 44038193152
    assert avail == 0
    assert pct == 96  # recalculé depuis les octets, pas lu dans « Capacity »


def test_percentage_is_recomputed_not_read_from_capacity() -> None:
    """`df` compte la réserve root dans `Capacity` et arrondit au supérieur : il
    affiche « 100% » alors qu'il reste de la place. Trop imprécis pour un seuil."""
    out = (
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "/dev/sda1 1000 500 500 100% /\n"
    )
    parsed = parse_df(out)
    assert parsed is not None
    assert parsed[3] == 50  # et non 100


def test_reads_last_filesystem_line_on_fallback() -> None:
    """La commande a un fallback `||` : deux blocs peuvent sortir, on retient
    la dernière ligne exploitable."""
    out = (
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "/dev/sdb1 200 100 100 50% /var/lib/docker\n"
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "/dev/sda1 1000 900 100 90% /\n"
    )
    parsed = parse_df(out)
    assert parsed is not None
    assert parsed[0] == 1000
    assert parsed[3] == 90


def test_rejects_unusable_output() -> None:
    assert parse_df("") is None
    assert parse_df("df: /nope: No such file or directory") is None
    assert parse_df("Filesystem 1B-blocks Used Available Capacity Mounted on\n") is None


def test_rejects_zero_sized_filesystem() -> None:
    """Un total nul ferait une division par zéro — et n'a aucun sens."""
    out = (
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n"
        "tmpfs 0 0 0 - /dev\n"
    )
    assert parse_df(out) is None


def test_threshold_crossing_is_detectable() -> None:
    """Le seuil d'alerte (90 %) doit se lire directement sur la valeur rendue."""
    below = parse_df(
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n/dev/sda1 100 89 11 89% /\n"
    )
    at = parse_df(
        "Filesystem 1B-blocks Used Available Capacity Mounted on\n/dev/sda1 100 90 10 90% /\n"
    )
    assert below is not None and at is not None
    assert below[3] == 89
    assert at[3] == 90
