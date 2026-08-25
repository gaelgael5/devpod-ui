"""Ce qu'un profil pose sur une machine après sa création : recettes, services.

Séparé de la route de création pour être testable sans hyperviseur : la
création d'une VM ne se simule pas, l'application d'un profil si.

**Un échec n'interrompt jamais la séquence.** La machine, elle, est bien créée :
la détruire parce qu'une recette manque un groupe ou qu'un dépôt est
indisponible ferait perdre un clone réussi pour un défaut souvent trivial. On
signale, on continue, et l'utilisateur ré-applique après correction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import structlog

from ..config.models import HostConfig, MachineProfile
from ..recipes.host_apply import HostApplyError, apply_recipe_to_host
from ..recipes.models import RecipeMeta

_log = structlog.get_logger(__name__)

# Signature du canal d'exécution vers la machine (SSH), injecté pour les tests.
Runner = Callable[..., Awaitable[tuple[int, str, str]]]
# Lecture du script d'installation d'une recette, injectée de même.
ScriptReader = Callable[[str], str | None]


async def apply_profile_recipes(
    profile: MachineProfile,
    *,
    host: HostConfig,
    catalogue: dict[str, RecipeMeta],
    run: Runner,
    read_script: ScriptReader,
) -> AsyncIterator[str]:
    """Applique les recettes du profil, DANS L'ORDRE déclaré.

    L'ordre est celui du profil : une dépendance se pose avant celle qui
    l'utilise. Chaque recette reçoit les options saisies au profil.
    """
    if not profile.recipes:
        return

    # Le catalogue est indexé par id ; le profil référence par key, seule stable.
    par_key = {meta.key: meta for meta in catalogue.values()}

    for entree in profile.recipes:
        meta = par_key.get(entree.key)
        if meta is None:
            # Une recette retirée du catalogue depuis la création du profil : on
            # le dit plutôt que d'échouer, le reste du profil garde son sens.
            yield f"==> AVERTISSEMENT : recette {entree.key} absente du catalogue, ignoree\n"
            _log.warning("profile_recipe_missing", key=entree.key, host=host.name)
            continue

        script = read_script(meta.id)
        if script is None:
            yield f"==> AVERTISSEMENT : recette {meta.id!r} sans install.sh, ignoree\n"
            continue

        yield f"==> Recette {meta.id} ({meta.version})...\n"
        try:
            resultat = await apply_recipe_to_host(
                meta,
                host_usage=host.usage,
                script=script,
                run=run,
                options=dict(entree.options),
            )
        except HostApplyError as exc:
            # Signale et poursuit : la machine reste utilisable, et la recette
            # se re-applique depuis sa fiche une fois la cause levee.
            yield f"==> ECHEC de la recette {meta.id} : {exc}\n"
            _log.warning("profile_recipe_failed", recipe=meta.id, host=host.name, exc=repr(exc))
            continue

        if resultat.changed:
            yield f"==> Recette {meta.id} posee.\n"
        else:
            yield f"==> Recette {meta.id} deja presente dans cette version.\n"


# Déploiement d'un template compose, injecté pour les tests : `deploy` parle à
# une vraie machine par SSH.
Deployer = Callable[..., Awaitable[object]]


async def deploy_profile_services(
    profile: MachineProfile,
    *,
    host: HostConfig,
    templates: dict[str, object],
    deploy: Deployer,
    already_deployed: Callable[[str], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Démarre les services déclarés par le profil, DANS L'ORDRE.

    L'ordre compte : un collecteur peut devoir démarrer avant ce qu'il observe.

    Ne redéploie jamais un service déjà présent sous ce nom — même règle que
    l'auto-start : idempotence signifie ne rien faire, pas écraser. Un échec
    n'interrompt pas la suite, pour la même raison que les recettes.
    """
    if not profile.services:
        return

    for service in profile.services:
        modele = templates.get(service.template_id)
        if modele is None:
            # Template retiré de la galerie depuis la création du profil.
            yield (
                f"==> AVERTISSEMENT : template {service.template_id!r} absent "
                "de la galerie, ignore\n"
            )
            _log.warning(
                "profile_service_template_missing",
                template=service.template_id,
                host=host.name,
            )
            continue

        if await already_deployed(service.deployment_id):
            yield f"==> Service {service.deployment_id} deja deploye.\n"
            continue

        yield f"==> Service {service.deployment_id} ({service.template_id})...\n"
        try:
            await deploy(
                name=service.deployment_id,
                template=modele,
                node_id=host.name,
                env_values=dict(service.params),
            )
        except Exception as exc:
            yield f"==> ECHEC du service {service.deployment_id} : {exc}\n"
            _log.warning(
                "profile_service_failed",
                service=service.deployment_id,
                host=host.name,
                exc=repr(exc),
            )
            continue

        yield f"==> Service {service.deployment_id} demarre.\n"
