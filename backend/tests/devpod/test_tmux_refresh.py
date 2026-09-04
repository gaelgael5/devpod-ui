"""Commande de repaint plein écran d'un terminal tmux (bouton « Rafraîchir »).

Le nudge ±1 ligne ne peut pas effacer les résidus déjà peints : le redessin de
tmux est différentiel, il ne renvoie que ce qui diffère de son image serveur, et
les résidus vivent côté navigateur. Seul un `refresh-client`, qui retransmet TOUT
l'écran au client (comme le fait un `attach`, c.-à-d. un F5), les efface — sans
resize, sans reconnexion, sans flash.
"""

from __future__ import annotations

from portal.devpod.exec import tmux_refresh_command


def test_cible_les_clients_de_la_session_et_les_rafraichit():
    sock = "TMUX_SOCK=$(find ...)"
    prefix = 'tmux ${TMUX_SOCK:+-S "$TMUX_SOCK"}'
    cmd = tmux_refresh_command(sock, prefix, "dev")

    # La détection de socket court d'abord.
    assert cmd.startswith(sock)
    # On liste les clients DE CETTE session, puis on rafraîchit chacun.
    assert "list-clients -t dev" in cmd
    assert "refresh-client -t" in cmd
    # Le nom de client passe par une variable citée : jamais interpolé en dur.
    assert '"$c"' in cmd


def test_nom_de_session_shell_quote():
    """Un nom de session ne doit jamais s'échapper de son argument."""
    cmd = tmux_refresh_command("S", "tmux", "a; rm -rf /")
    assert "a; rm -rf /" not in cmd.replace("'a; rm -rf /'", "")
    assert "'a; rm -rf /'" in cmd
