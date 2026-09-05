"""Exécuteur de provisioning Proxmox : le contrat `Executeur`, en vrai.

La création passe par les **scripts d'hyperviseur existants** — la même chaîne
que les VM de test (spec du type, paramètres du profil de machine, exécution
SSH sur l'hyperviseur, JSON final) : réinventer un chemin d'appel à `qm`
ferait diverger deux provisioning du même parc.

Ce que ce module ajoute à cette chaîne, et qui n'existe pas côté test :

- **le VMID est alloué automatiquement** (`pvesh get /cluster/nextid`) — aucun
  humain ne choisit un numéro à la souscription ;
- **le nom est dérivé du VMID** (`ded-<vmid>` / `mut-<vmid>`) : unique dans le
  cluster, sans compteur à tenir ;
- **le rattachement est persisté** dans la même transaction que la machine —
  propriété (`host_ownership`) pour le dédié, part (`subscription_hosts`) pour
  le pool. Une machine sans rattachement serait orpheline.

L'idempotence ne vit PAS ici : l'orchestrateur refuse déjà de reprovisionner un
abonnement servi, et le registre refuse un événement rejoué. Ce module peut donc
monter sans se demander s'il l'a déjà fait.
"""

from __future__ import annotations

import structlog

from ..config.models import GlobalConfig, HostConfig, Hypervisor
from .cible import Cible
from .orchestration import HostProvisionne

log = structlog.get_logger(__name__)


class ProvisioningImpossible(RuntimeError):
    """Échec exploitable : le message part dans `provisioning_runs.erreur`."""


class ExecuteurProxmox:
    """Implémente `billing.orchestration.Executeur` contre le parc réel.

    Les trois opérations d'infrastructure (`_spec`, `_prochain_vmid`,
    `_executer_commandes`) sont des méthodes surchargées par les tests : la
    logique — préparation des arguments, persistance, rattachement — se prouve
    sans SSH ni Proxmox ; seul le test d'intégration exerce le vrai parc.
    """

    async def creer_vm_dediee(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, noeud: str, cible: Cible
    ) -> HostProvisionne:
        return await self._monter(
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            cible=cible,
            mutualise=False,
        )

    async def creer_host_mutualise(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, cible: Cible
    ) -> HostProvisionne:
        return await self._monter(
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            cible=cible,
            mutualise=True,
        )

    async def assigner_host(
        self, *, subscription_id: str, owner_login: str, offer_slug: str, host_name: str
    ) -> HostProvisionne:
        """Donne à l'abonnement sa place sur une machine du pool qui existe déjà."""
        from sqlalchemy import select

        from ..db.billing_offers import get_offer
        from ..db.engine import _get_engine
        from ..db.subscription_hosts import rattacher
        from ..db.tables import hosts

        async with _get_engine().begin() as conn:
            offre = await get_offer(offer_slug, conn)
            await rattacher(
                subscription_id, host_name, offre.max_workspaces if offre else None, conn
            )
            capacite = (
                await conn.execute(
                    select(hosts.c.capacity_workspaces).where(hosts.c.name == host_name)
                )
            ).scalar_one_or_none()
        log.info(
            "provisioning_place_assignee",
            subscription_id=subscription_id,
            host=host_name,
            owner=owner_login,
        )
        return HostProvisionne(host_name=host_name, capacity_workspaces=capacite)

    # ─── Montage d'une machine neuve ─────────────────────────────────────────

    async def _monter(
        self,
        *,
        subscription_id: str,
        owner_login: str,
        offer_slug: str,
        cible: Cible,
        mutualise: bool,
    ) -> HostProvisionne:
        from ..config.store import load_global
        from ..db.engine import _get_engine
        from ..db.host_profiles import get_host_profile
        from ..db.machine_profiles import get_profile

        cfg = load_global()
        node = next((n for n in cfg.hypervisors if n.name == cible.hypervisor), None)
        if node is None:
            raise ProvisioningImpossible(
                f"hyperviseur {cible.hypervisor!r} introuvable dans la configuration"
            )

        async with _get_engine().connect() as conn:
            profil_machine = await get_profile(cible.machine_profile, conn)
            profil_host = await get_host_profile(cible.host_profile, conn)
        if profil_machine is None:
            raise ProvisioningImpossible(f"profil de machine {cible.machine_profile!r} introuvable")
        capacite = profil_host.capacity_workspaces() if profil_host else None

        spec = await self._spec(node, cfg)
        vmid = await self._prochain_vmid(node)
        nom = f"{'mut' if mutualise else 'ded'}-{vmid}"
        commandes = self._commandes(spec, profil_machine.params, cfg, node, vmid, nom)

        sortie = await self._executer_commandes(node, commandes, vmid=vmid, nom=nom)
        hote = self._machine_creee(sortie, cible, vmid, nom, capacite, mutualise)

        await self._persister(
            hote,
            subscription_id=subscription_id,
            owner_login=owner_login,
            offer_slug=offer_slug,
            mutualise=mutualise,
        )
        log.info(
            "provisioning_machine_montee",
            host=hote.name,
            vmid=vmid,
            mutualise=mutualise,
            subscription_id=subscription_id,
            owner=owner_login,
        )
        return HostProvisionne(host_name=hote.name, capacity_workspaces=capacite)

    def _commandes(
        self,
        spec: dict[str, object],
        params_profil: dict[str, str],
        cfg: GlobalConfig,
        node: Hypervisor,
        vmid: str,
        nom: str,
    ) -> list[str]:
        """Les commandes du script, arguments résolus — ou un échec actionnable."""
        from ..routes.proxmox import (
            _substitute,
            find_identifier_arg,
            missing_placeholders,
            spec_arg_defaults,
        )
        from ..settings import get_settings

        identifiant = find_identifier_arg(spec)
        if identifiant is None:
            raise ProvisioningImpossible(
                "la spec du type d'hyperviseur ne déclare pas d'argument identifiant (VMID)"
            )
        # Défauts de la spec, surchargés par le profil de machine — même règle
        # que les VM de test : un argument ajouté à la spec après coup
        # s'applique même si le profil n'a pas été re-saisi.
        args = {**spec_arg_defaults(spec), **params_profil}
        args[identifiant] = vmid
        args["NODE_NAME"] = nom
        args["PORTAL_URL"] = cfg.server.external_url
        args["PORTAL_TOKEN"] = get_settings().portal_api_key
        args["PORTAL_PVE_NODE"] = node.name

        brutes: list[str] = spec.get("commands", [])  # type: ignore[assignment]
        manquants = missing_placeholders(brutes, args)
        if manquants:
            raise ProvisioningImpossible(
                f"paramètres manquants pour le profil de machine : "
                f"{', '.join(sorted(manquants))} — les renseigner dans le profil "
                "ou les paramètres du type d'hyperviseur"
            )
        return [_substitute(c, args) for c in brutes]

    def _machine_creee(
        self,
        sortie: str,
        cible: Cible,
        vmid: str,
        nom: str,
        capacite: int | None,
        mutualise: bool,
    ) -> HostConfig:
        """Le JSON final du script → la machine du parc, `usage=workspaces`."""
        from ..devpod.test_vm import parse_last_json

        resultat = parse_last_json(sortie)
        if resultat is None:
            raise ProvisioningImpossible(
                "le script de création n'a pas rendu de résultat JSON — "
                f"fin de sortie : {sortie[-500:]!r}"
            )
        from ..devpod.test_vm import resultat_en_erreur

        erreur_script = resultat_en_erreur(resultat)
        if erreur_script is not None:
            raise ProvisioningImpossible(f"le script de création a échoué : {erreur_script}")
        adresse = str(resultat.get("address") or "")
        utilisateur = str(resultat.get("ssh_user") or "debian")
        if resultat.get("type") == "docker-tls":
            type_hote: str = "docker-tls"
            docker_host = str(resultat.get("docker_host") or f"tcp://{adresse}:2376")
            adresse_finale = ""
        else:
            type_hote = "ssh"
            docker_host = ""
            adresse_finale = f"{utilisateur}@{adresse}" if adresse else ""
        return HostConfig(
            name=str(resultat.get("name") or nom),
            type=type_hote,  # type: ignore[arg-type]
            docker_host=docker_host,
            address=adresse_finale,
            vmid=str(resultat.get("vmid") or vmid),
            proxmox_node=str(resultat.get("proxmox_node") or cible.noeud),
            usage="workspaces",
            profile_slug=cible.machine_profile,
            capacity_workspaces=capacite,
            accepts_mutualise=mutualise,
            hypervisor=cible.hypervisor,
        )

    async def _persister(
        self,
        hote: HostConfig,
        *,
        subscription_id: str,
        owner_login: str,
        offer_slug: str,
        mutualise: bool,
    ) -> None:
        """Machine + rattachement, dans la MÊME transaction.

        L'ordre des fautes possibles est choisi : une machine enregistrée sans
        rattachement serait orpheline en silence ; une transaction refusée
        laisse une VM à réconcilier mais une ligne `provisioning_runs` en échec,
        visible et rejouable.
        """
        from ..config.store import load_global
        from ..db.billing_offers import get_offer
        from ..db.engine import _get_engine
        from ..db.global_config import save_global_db, set_cached_global
        from ..db.host_ownership import poser_propriete
        from ..db.subscription_hosts import rattacher

        parc = load_global()
        if any(h.name == hote.name for h in parc.hosts):
            raise ProvisioningImpossible(
                f"un host nommé {hote.name!r} existe déjà — la VM {hote.vmid} est à réconcilier"
            )
        parc.hosts.append(hote)

        async with _get_engine().begin() as conn:
            await save_global_db(parc, conn)
            offre = await get_offer(offer_slug, conn)
            quota = offre.max_workspaces if offre else None
            if mutualise:
                # Pas de propriétaire : une machine du pool n'en a pas
                # (migration 117). La part de l'abonné suffit.
                await rattacher(subscription_id, hote.name, quota, conn)
            else:
                await poser_propriete(
                    host_name=hote.name,
                    owner_login=owner_login,
                    offer_slug=offer_slug,
                    offer_max_workspaces=quota,
                    conn=conn,
                )
                # Part sans plafond commercial : en dédié, la capacité physique
                # gouverne seule (le quota est figé sur la propriété).
                await rattacher(subscription_id, hote.name, None, conn)
        set_cached_global(parc)  # après commit réussi seulement (bug 034)

    # ─── Opérations d'infrastructure (surchargées par les tests) ─────────────

    async def _spec(self, node: Hypervisor, cfg: GlobalConfig) -> dict[str, object]:
        from fastapi import HTTPException

        from ..routes.proxmox import _fetch_spec

        try:
            return await _fetch_spec(node, cfg)
        except HTTPException as exc:
            # L'aide de route n'a pas sa place dans une trace de provisioning :
            # on garde le motif, pas le code HTTP.
            raise ProvisioningImpossible(str(exc.detail)) from exc

    async def _prochain_vmid(self, node: Hypervisor) -> str:
        from ..routes.proxmox import _ssh_run

        sortie = (await _ssh_run(node, "pvesh get /cluster/nextid")).strip()
        vmid = sortie.splitlines()[-1].strip() if sortie else ""
        if not vmid.isdigit():
            raise ProvisioningImpossible(
                f"l'hyperviseur n'a pas rendu de VMID libre : {sortie[-200:]!r}"
            )
        return vmid

    async def _executer_commandes(
        self, node: Hypervisor, commandes: list[str], *, vmid: str, nom: str
    ) -> str:
        """Exécute le script de création et rend sa sortie complète.

        Chaque ligne part aussi dans les journaux : la progression d'un clone
        se lit en centralisé, comme celle des VM de test.
        """
        from ..routes.proxmox import _ssh_stream

        tampon = bytearray()
        ligne = ""
        async for morceau in _ssh_stream(node, commandes):
            tampon.extend(morceau)
            ligne += morceau.decode("utf-8", errors="replace")
            while "\n" in ligne:
                courante, ligne = ligne.split("\n", 1)
                if courante.strip():
                    log.info("provisioning_vm_out", vmid=vmid, host=nom, line=courante.rstrip("\r"))
        if ligne.strip():
            log.info("provisioning_vm_out", vmid=vmid, host=nom, line=ligne.rstrip("\r"))
        return tampon.decode("utf-8", errors="replace")
