"""Les templates transactionnels Listmonk — source de vérité versionnée.

Rédactions issues de `docs/emails-abonnement/` (validées le 05/09/2026) : six
messages × deux cultures. Syntaxe Go template de Listmonk (`{{ .Tx.Data.* }}`),
sujet ET corps rendus par Listmonk avec le payload composé par `service.py`.

Ils sont poussés vers l'instance par l'action admin « sync-templates » — jamais
au démarrage (même règle que la synchro des recettes : choix admin). Le nom
`abonnement-<message>-<culture>` est le contrat entre le portail et Listmonk.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Les messages ayant un template. `avertissement_destruction` n'est pas un
#: EventKind du canal : c'est le dernier filet du balayeur de rétention.
MESSAGES = (
    "debut_essai",
    "activation",
    "renouvellement",
    "echec_paiement",
    "resiliation",
    "avertissement_destruction",
)


@dataclass(frozen=True)
class TemplateEmail:
    sujet: str
    corps: str


def nom_template(message: str, culture: str) -> str:
    return f"abonnement-{message.replace('_', '-')}-{culture}"


_P = '<p style="margin:0 0 12px 0">'
_FIN = "</p>"


def _corps(*paragraphes: str) -> str:
    html = "".join(f"{_P}{p}{_FIN}" for p in paragraphes)
    return (
        '<div style="font-family:sans-serif;max-width:560px;margin:0 auto;'
        f'line-height:1.5">{html}</div>'
    )


TEMPLATES: dict[tuple[str, str], TemplateEmail] = {
    # ── debut_essai ──────────────────────────────────────────────────────────
    ("debut_essai", "fr"): TemplateEmail(
        sujet="Votre essai {{ .Tx.Data.offre_label }} est ouvert — "
        "jusqu'au {{ .Tx.Data.essai_fin_date }}",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "Votre période d'essai du forfait <strong>{{ .Tx.Data.offre_label }}"
            "</strong> est ouverte. Elle est gratuite et se termine le "
            "<strong>{{ .Tx.Data.essai_fin_date }}</strong> "
            "({{ .Tx.Data.essai_duree_jours }} jours).",
            "Vos workspaces de développement (VS Code dans le navigateur, rien à "
            "installer), vos dépôts Git, vos secrets et vos outils IA vous "
            'attendent : <a href="{{ .Tx.Data.lien_portail }}">commencer</a>.',
            "Et le {{ .Tx.Data.essai_fin_date }} ? "
            "{{ if .Tx.Data.tacite_reconduction }}Votre abonnement démarrera "
            "automatiquement au tarif de {{ .Tx.Data.prix_formate }} / "
            "{{ .Tx.Data.periodicite }}. Vous pouvez l'annuler à tout moment "
            "avant cette date, en deux clics, sans justification : "
            '<a href="{{ .Tx.Data.lien_abonnement }}">gérer mon abonnement</a>.'
            "{{ else }}Rien ne sera facturé : l'essai s'arrête simplement, et vos "
            "données restent récupérables pendant {{ .Tx.Data.recuperation_jours }} "
            "jours si vous souscrivez ensuite.{{ end }}",
            "Une question ? Répondez simplement à ce message"
            "{{ if .Tx.Data.email_support }} ({{ .Tx.Data.email_support }}){{ end }}.",
            "L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("debut_essai", "en"): TemplateEmail(
        sujet="Your {{ .Tx.Data.offre_label }} trial is live — until {{ .Tx.Data.essai_fin_date }}",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "Your free trial of the <strong>{{ .Tx.Data.offre_label }}</strong> "
            "plan has started. It ends on <strong>{{ .Tx.Data.essai_fin_date }}"
            "</strong> ({{ .Tx.Data.essai_duree_jours }} days).",
            "Your development workspaces (VS Code in the browser, nothing to "
            "install), Git repositories, secrets and AI tools are ready: "
            '<a href="{{ .Tx.Data.lien_portail }}">get started</a>.',
            "What happens on {{ .Tx.Data.essai_fin_date }}? "
            "{{ if .Tx.Data.tacite_reconduction }}Your subscription will start "
            "automatically at {{ .Tx.Data.prix_formate }} / "
            "{{ .Tx.Data.periodicite }}. You can cancel anytime before that "
            "date, in two clicks, no questions asked: "
            '<a href="{{ .Tx.Data.lien_abonnement }}">manage my subscription</a>.'
            "{{ else }}Nothing will be charged: the trial simply ends, and your "
            "data stays recoverable for {{ .Tx.Data.recuperation_jours }} days "
            "if you subscribe later.{{ end }}",
            "Questions? Just reply to this message"
            "{{ if .Tx.Data.email_support }} ({{ .Tx.Data.email_support }}){{ end }}.",
            "The {{ .Tx.Data.produit }} team",
        ),
    ),
    # ── activation ───────────────────────────────────────────────────────────
    ("activation", "fr"): TemplateEmail(
        sujet="Votre abonnement {{ .Tx.Data.offre_label }} est actif",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "Votre abonnement <strong>{{ .Tx.Data.offre_label }}</strong> est "
            "actif : le paiement de {{ .Tx.Data.prix_formate }} a bien été reçu "
            "le {{ .Tx.Data.paiement_date }}"
            "{{ if .Tx.Data.moyen_paiement }} ({{ .Tx.Data.moyen_paiement }})"
            "{{ end }}.",
            "Prochaine échéance : le "
            "<strong>{{ .Tx.Data.prochaine_echeance_date }}</strong>, même "
            "montant, prélevé automatiquement.",
            '<a href="{{ .Tx.Data.lien_facture }}">Votre facture</a> · '
            '<a href="{{ .Tx.Data.lien_abonnement }}">gérer l\'abonnement</a> '
            "(moyen de paiement, résiliation).",
            "Merci de votre confiance,<br>L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("activation", "en"): TemplateEmail(
        sujet="Your {{ .Tx.Data.offre_label }} subscription is active",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "Your <strong>{{ .Tx.Data.offre_label }}</strong> subscription is "
            "active: the {{ .Tx.Data.prix_formate }} payment was received on "
            "{{ .Tx.Data.paiement_date }}"
            "{{ if .Tx.Data.moyen_paiement }} ({{ .Tx.Data.moyen_paiement }})"
            "{{ end }}.",
            "Next renewal: <strong>{{ .Tx.Data.prochaine_echeance_date }}"
            "</strong>, same amount, charged automatically.",
            '<a href="{{ .Tx.Data.lien_facture }}">Your invoice</a> · '
            '<a href="{{ .Tx.Data.lien_abonnement }}">manage your subscription'
            "</a> (payment method, cancellation).",
            "Thank you for your trust,<br>The {{ .Tx.Data.produit }} team",
        ),
    ),
    # ── renouvellement — un reçu, pas une relance ────────────────────────────
    ("renouvellement", "fr"): TemplateEmail(
        sujet="Reçu — {{ .Tx.Data.offre_label }}, {{ .Tx.Data.prix_formate }} "
        "le {{ .Tx.Data.paiement_date }}",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "Votre abonnement <strong>{{ .Tx.Data.offre_label }}</strong> a été "
            "reconduit : {{ .Tx.Data.prix_formate }} prélevés le "
            "{{ .Tx.Data.paiement_date }}"
            "{{ if .Tx.Data.moyen_paiement }} ({{ .Tx.Data.moyen_paiement }})"
            "{{ end }}.",
            '<a href="{{ .Tx.Data.lien_facture }}">Facture</a> · prochaine '
            "échéance le {{ .Tx.Data.prochaine_echeance_date }} · "
            '<a href="{{ .Tx.Data.lien_abonnement }}">gérer l\'abonnement</a>.',
            "L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("renouvellement", "en"): TemplateEmail(
        sujet="Receipt — {{ .Tx.Data.offre_label }}, {{ .Tx.Data.prix_formate }} "
        "on {{ .Tx.Data.paiement_date }}",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "Your <strong>{{ .Tx.Data.offre_label }}</strong> subscription was "
            "renewed: {{ .Tx.Data.prix_formate }} charged on "
            "{{ .Tx.Data.paiement_date }}"
            "{{ if .Tx.Data.moyen_paiement }} ({{ .Tx.Data.moyen_paiement }})"
            "{{ end }}.",
            '<a href="{{ .Tx.Data.lien_facture }}">Invoice</a> · next renewal '
            "on {{ .Tx.Data.prochaine_echeance_date }} · "
            '<a href="{{ .Tx.Data.lien_abonnement }}">manage your subscription</a>.',
            "The {{ .Tx.Data.produit }} team",
        ),
    ),
    # ── echec_paiement — arrêté n'est PAS supprimé ───────────────────────────
    ("echec_paiement", "fr"): TemplateEmail(
        sujet="Action requise — le paiement de votre abonnement "
        "{{ .Tx.Data.offre_label }} a échoué",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "Le prélèvement de {{ .Tx.Data.prix_formate }} du "
            "{{ .Tx.Data.echec_date }} n'a pas abouti"
            "{{ if .Tx.Data.echec_motif }} ({{ .Tx.Data.echec_motif }}){{ end }}.",
            "Dès maintenant : vos workspaces sont <strong>arrêtés — ils ne sont "
            "PAS supprimés</strong>. Vos données, dépôts et configurations sont "
            "intacts.",
            "Tout reste récupérable jusqu'au "
            "<strong>{{ .Tx.Data.date_limite_recuperation }}</strong> "
            "({{ .Tx.Data.recuperation_jours }} jours). Mettre à jour votre "
            "moyen de paiement rétablit l'accès immédiatement : "
            '<a href="{{ .Tx.Data.lien_paiement }}">mettre à jour</a>.',
            "Après cette date, vos workspaces seront supprimés"
            "{{ if .Tx.Data.avertissement_avant_destruction }} — vous recevrez "
            "un dernier avertissement avant{{ end }}.",
            "Un souci avec le paiement ? Répondez-nous"
            "{{ if .Tx.Data.email_support }} ({{ .Tx.Data.email_support }}){{ end }}.",
            "L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("echec_paiement", "en"): TemplateEmail(
        sujet="Action required — payment for your {{ .Tx.Data.offre_label }} subscription failed",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "The {{ .Tx.Data.prix_formate }} charge on {{ .Tx.Data.echec_date }} "
            "did not go through"
            "{{ if .Tx.Data.echec_motif }} ({{ .Tx.Data.echec_motif }}){{ end }}.",
            "Effective now: your workspaces are <strong>stopped — they are NOT "
            "deleted</strong>. Your data, repositories and configurations are "
            "intact.",
            "Everything stays recoverable until "
            "<strong>{{ .Tx.Data.date_limite_recuperation }}</strong> "
            "({{ .Tx.Data.recuperation_jours }} days). Updating your payment "
            "method restores access immediately: "
            '<a href="{{ .Tx.Data.lien_paiement }}">update it</a>.',
            "After that date, your workspaces will be deleted"
            "{{ if .Tx.Data.avertissement_avant_destruction }} — you will get "
            "one final warning first{{ end }}.",
            "Payment trouble? Just reply"
            "{{ if .Tx.Data.email_support }} ({{ .Tx.Data.email_support }}){{ end }}.",
            "The {{ .Tx.Data.produit }} team",
        ),
    ),
    # ── resiliation — réversible, et pas une suppression de compte ───────────
    ("resiliation", "fr"): TemplateEmail(
        sujet="Votre abonnement {{ .Tx.Data.offre_label }} est résilié — "
        "données récupérables jusqu'au {{ .Tx.Data.date_limite_recuperation }}",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "C'est confirmé : votre abonnement <strong>"
            "{{ .Tx.Data.offre_label }}</strong> est résilié"
            "{{ if .Tx.Data.fin_acces_date }} et votre accès reste ouvert "
            "jusqu'au {{ .Tx.Data.fin_acces_date }}, déjà payé{{ end }}. "
            "Aucun prélèvement n'aura plus lieu.",
            "Votre compte reste ouvert — résilier n'est pas supprimer son "
            "compte. Vos workspaces sont arrêtés, <strong>PAS supprimés</strong> : "
            "tout reste récupérable jusqu'au "
            "<strong>{{ .Tx.Data.date_limite_recuperation }}</strong> "
            "({{ .Tx.Data.recuperation_jours }} jours).",
            "Vous changez d'avis ? Une résiliation est réversible : "
            '<a href="{{ .Tx.Data.lien_offres }}">re-souscrivez</a> avant le '
            "{{ .Tx.Data.date_limite_recuperation }} et vous retrouvez vos "
            "workspaces exactement comme vous les avez laissés.",
            "Si quelque chose vous a déplu, dites-le-nous en répondant à ce "
            "message — ça nous aide vraiment.",
            "L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("resiliation", "en"): TemplateEmail(
        sujet="Your {{ .Tx.Data.offre_label }} subscription is cancelled — "
        "data recoverable until {{ .Tx.Data.date_limite_recuperation }}",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "Confirmed: your <strong>{{ .Tx.Data.offre_label }}</strong> "
            "subscription is cancelled"
            "{{ if .Tx.Data.fin_acces_date }} and your access stays open until "
            "{{ .Tx.Data.fin_acces_date }}, already paid for{{ end }}. "
            "No further charges will occur.",
            "Your account stays open — cancelling is not deleting your account. "
            "Your workspaces are stopped, <strong>NOT deleted</strong>: "
            "everything stays recoverable until "
            "<strong>{{ .Tx.Data.date_limite_recuperation }}</strong> "
            "({{ .Tx.Data.recuperation_jours }} days).",
            "Changed your mind? Cancellation is reversible: "
            '<a href="{{ .Tx.Data.lien_offres }}">subscribe again</a> before '
            "{{ .Tx.Data.date_limite_recuperation }} and you will find your "
            "workspaces exactly as you left them.",
            "If something put you off, tell us by replying to this message — it genuinely helps.",
            "The {{ .Tx.Data.produit }} team",
        ),
    ),
    # ── avertissement pré-destruction — le dernier filet ─────────────────────
    ("avertissement_destruction", "fr"): TemplateEmail(
        sujet="Dernier rappel — vos workspaces seront supprimés le {{ .Tx.Data.destruction_date }}",
        corps=_corps(
            "Bonjour {{ .Tx.Data.prenom_ou_login }},",
            "Dernier rappel, promis : le <strong>"
            "{{ .Tx.Data.destruction_date }}</strong>, soit dans "
            "{{ .Tx.Data.destruction_dans_jours }} jours, vos workspaces et "
            "leurs données seront définitivement supprimés — dépôts non "
            "poussés, configurations, fichiers de travail compris. Cette "
            "suppression est <strong>irréversible</strong>.",
            "Ce qui sera supprimé :"
            "<ul>{{ if .Tx.Data.machines }}{{ range .Tx.Data.machines }}"
            "<li>{{ . }}</li>{{ end }}{{ else }}"
            "<li>l'ensemble de vos espaces de travail</li>{{ end }}</ul>",
            "Pour tout conserver, il suffit de "
            '{{ if eq .Tx.Data.etat "echec_paiement" }}'
            '<a href="{{ .Tx.Data.lien_paiement }}">mettre à jour votre moyen '
            "de paiement</a>{{ else }}"
            '<a href="{{ .Tx.Data.lien_offres }}">re-souscrire</a>{{ end }} — '
            "l'accès est rétabli immédiatement, rien n'est perdu.",
            "Vous préférez récupérer vos fichiers sans re-souscrire ? Répondez "
            "à ce message avant le {{ .Tx.Data.destruction_date }}.",
            "L'équipe {{ .Tx.Data.produit }}",
        ),
    ),
    ("avertissement_destruction", "en"): TemplateEmail(
        sujet="Final reminder — your workspaces will be deleted on {{ .Tx.Data.destruction_date }}",
        corps=_corps(
            "Hello {{ .Tx.Data.prenom_ou_login }},",
            "Final reminder, we promise: on <strong>"
            "{{ .Tx.Data.destruction_date }}</strong>, in "
            "{{ .Tx.Data.destruction_dans_jours }} days, your workspaces and "
            "their data will be permanently deleted — unpushed repositories, "
            "configurations and working files included. This deletion is "
            "<strong>irreversible</strong>.",
            "What will be deleted:"
            "<ul>{{ if .Tx.Data.machines }}{{ range .Tx.Data.machines }}"
            "<li>{{ . }}</li>{{ end }}{{ else }}"
            "<li>all of your workspaces</li>{{ end }}</ul>",
            "To keep everything, simply "
            '{{ if eq .Tx.Data.etat "echec_paiement" }}'
            '<a href="{{ .Tx.Data.lien_paiement }}">update your payment '
            "method</a>{{ else }}"
            '<a href="{{ .Tx.Data.lien_offres }}">subscribe again</a>{{ end }} '
            "— access is restored immediately, nothing is lost.",
            "You would rather retrieve your files without subscribing? Reply to "
            "message before {{ .Tx.Data.destruction_date }}.",
            "The {{ .Tx.Data.produit }} team",
        ),
    ),
}
