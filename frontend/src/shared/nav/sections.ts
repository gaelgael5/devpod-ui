/**
 * Regroupements d'ecrans d'administration — source unique.
 *
 * Le meme tableau sert au sous-menu du profil ET a la barre de liens posee en
 * haut des ecrans concernes. Deux listes separees auraient diverge au premier
 * ecran ajoute : un lien present dans le menu, absent de la barre, sans que
 * personne ne s'en apercoive.
 */

export interface LienSection {
  path: string
  /** Clef i18n du libelle — le meme que celui du menu. */
  labelKey: string
}

export interface Section {
  /** Clef i18n du titre du groupe. */
  titleKey: string
  liens: LienSection[]
}

export const SECTION_MACHINES: Section = {
  titleKey: 'admin.machinesMenu',
  liens: [
    { path: '/admin/hypervisor-types', labelKey: 'admin.hypervisorTypes' },
    { path: '/admin/hypervisors', labelKey: 'admin.hypervisors' },
    { path: '/admin/hosts', labelKey: 'admin.hosts' },
    { path: '/admin/machine-profiles', labelKey: 'admin.machineProfiles.navLabel' },
  ],
}

export const SECTION_FORFAITS: Section = {
  titleKey: 'admin.plansMenu',
  liens: [
    { path: '/admin/host-profiles', labelKey: 'admin.hostProfiles.navLabel' },
    { path: '/admin/billing-catalog', labelKey: 'admin.billing.navLabel' },
    { path: '/admin/billing-offers', labelKey: 'admin.offers.navLabel' },
  ],
}

export const SECTIONS: Section[] = [SECTION_MACHINES, SECTION_FORFAITS]

/**
 * Section a laquelle appartient un chemin, s'il y en a une.
 *
 * Comparaison sur le chemin exact : `/admin/hosts` et `/admin/host-profiles`
 * sont deux ecrans distincts de deux groupes distincts, un test par prefixe
 * les confondrait.
 */
export function sectionDe(pathname: string): Section | null {
  return SECTIONS.find((s) => s.liens.some((l) => l.path === pathname)) ?? null
}
