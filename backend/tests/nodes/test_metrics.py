"""Sonde d'occupation disque des hosts.

Le parsing de `df` est la partie fragile : format variable selon l'implémentation,
noms de device longs qui font passer la ligne à la ligne, réserve root qui fausse
la colonne `Capacity`. Un mauvais parsing donne une alerte fantôme — ou pire, un
silence sur un disque plein (incident du 17/08 : host-dev-01 à 100 %, zéro alerte).
"""

from __future__ import annotations

from portal.nodes.metrics import parse_df

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


# ─── Mémoire et charge CPU (mêmes sonde et connexion SSH que le disque) ───────

from portal.nodes.metrics import _section, parse_loadavg, parse_meminfo  # noqa: E402

MEMINFO = """MemTotal:       16333372 kB
MemFree:          521840 kB
MemAvailable:    9876543 kB
Buffers:          123456 kB
Cached:          6543210 kB
"""


def test_memory_used_excludes_reclaimable_cache() -> None:
    """« Utilisé » = total − MemAvailable, PAS total − MemFree : le cache est
    récupérable, le compter comme occupé afficherait ~97 % sur une machine saine."""
    parsed = parse_meminfo(MEMINFO)
    assert parsed is not None
    total, used = parsed
    assert total == 16333372 * 1024
    assert used == (16333372 - 9876543) * 1024
    # Le calcul naïf (total − MemFree) donnerait un tout autre chiffre.
    assert used != (16333372 - 521840) * 1024


def test_memory_needs_both_total_and_available() -> None:
    assert parse_meminfo("") is None
    assert parse_meminfo("MemTotal: 100 kB\n") is None  # MemAvailable absent
    assert parse_meminfo("MemAvailable: 100 kB\n") is None


def test_load_is_normalised_by_core_count() -> None:
    """Une charge de 4 sur 8 cœurs = 50 %, comparable d'une machine à l'autre."""
    parsed = parse_loadavg("4.00 3.10 2.50 2/300 1234\n8\n")
    assert parsed == (4.0, 8)


def test_load_rejects_incomplete_output() -> None:
    assert parse_loadavg("") is None
    assert parse_loadavg("4.00 3.10 2.50 2/300 1234\n") is None  # nproc manquant
    assert parse_loadavg("pas-un-nombre\n8\n") is None


def test_sections_are_isolated() -> None:
    """Les trois mesures arrivent dans une seule sortie : le découpage ne doit
    pas laisser une section déborder sur la suivante."""
    out = "@@DF\nligne-df\n@@MEM\nligne-mem\n@@CPU\nligne-cpu\n"
    assert _section(out, "DF").strip() == "ligne-df"
    assert _section(out, "MEM").strip() == "ligne-mem"
    assert _section(out, "CPU").strip() == "ligne-cpu"
    assert _section(out, "ABSENT") == ""


# ─── Cadences distinctes servies par une seule boucle ────────────────────────

from portal.nodes.metrics import build_command, due_sections  # noqa: E402


def test_command_carries_only_requested_sections() -> None:
    """Un tick CPU (30 s) ne doit pas relire `df` sur toutes les machines."""
    cpu_only = build_command(["CPU"])
    assert "@@CPU" in cpu_only
    assert "@@DF" not in cpu_only
    assert "meminfo" not in cpu_only

    full = build_command(["DF", "MEM", "CPU"])
    assert "@@DF" in full and "@@MEM" in full and "@@CPU" in full


def test_due_sections_follows_each_cadence() -> None:
    """Chaque famille n'est relevée qu'à l'échéance de SA cadence."""
    # Rien d'échu : 10 s après le dernier relevé, seul le CPU (30 s) ne l'est pas encore.
    assert due_sections({"DF": 10, "MEM": 10, "CPU": 10}) == []
    # 40 s : le CPU seul.
    assert due_sections({"DF": 40, "MEM": 40, "CPU": 40}) == ["CPU"]
    # 6 min : mémoire + CPU, toujours pas le disque.
    assert set(due_sections({"DF": 400, "MEM": 400, "CPU": 400})) == {"MEM", "CPU"}
    # 2 h : tout.
    assert set(due_sections({"DF": 7200, "MEM": 7200, "CPU": 7200})) == {"DF", "MEM", "CPU"}


def test_everything_is_due_on_first_tick() -> None:
    """Au démarrage l'écran ne doit pas attendre une heure pour afficher le disque."""
    inf = float("inf")
    assert set(due_sections({"DF": inf, "MEM": inf, "CPU": inf})) == {"DF", "MEM", "CPU"}
