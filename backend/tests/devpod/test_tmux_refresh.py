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


def test_resynchronise_la_taille_avant_le_repaint():
    """SIGWINCH direct au client tmux AVANT le refresh-client.

    Mesuré en production le 05/09 : derrière `devpod ssh` (login root puis
    `su - <user>`), le client tmux n'a PAS de terminal de contrôle — le
    SIGWINCH émis par le TIOCSWINSZ du pont n'atteint personne, et le client
    garde sa taille d'attache (clavier mobile : écran figé à 28 lignes, ou
    dessiné à 49 dans 28). `kill -WINCH` sur `#{client_pid}` force le client à
    relire son tty (déjà à la bonne taille) — vérifié sur tmux 3.6.
    """
    cmd = tmux_refresh_command("S", "tmux", "dev")

    # Le coup de WINCH vise le pid du client, et part AVANT le repaint :
    # refresh-client retransmet l'écran à la taille que tmux croit — resynchroniser
    # après aurait repeint l'écran à l'ancienne taille.
    assert "#{client_pid}" in cmd
    assert "kill -WINCH" in cmd
    assert cmd.index("kill -WINCH") < cmd.index("refresh-client")
    # Entre les deux, un délai : le client doit avoir annoncé sa nouvelle
    # taille au serveur avant qu'on demande le repaint.
    assert "sleep" in cmd


def test_nom_de_session_shell_quote():
    """Un nom de session ne doit jamais s'échapper de son argument."""
    cmd = tmux_refresh_command("S", "tmux", "a; rm -rf /")
    assert "a; rm -rf /" not in cmd.replace("'a; rm -rf /'", "")
    assert "'a; rm -rf /'" in cmd
