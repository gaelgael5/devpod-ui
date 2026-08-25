/** Longueur maximale d'un slug, alignee sur la validation du serveur. */
const SLUG_MAX = 40

/**
 * Derive un slug depuis un libelle.
 *
 * Le serveur n'accepte que `^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$` : minuscules,
 * chiffres et tirets, ni au debut ni a la fin, 2 a 40 caracteres. Les accents
 * sont DECOMPOSES puis retires plutot que remplaces un a un — « é » devient
 * « e », et la regle vaut pour tout l'alphabet latin sans table de conversion.
 */
export function slugifier(label: string): string {
  return label
    .normalize('NFD')
    // Retire les diacritiques laissés par la décomposition.
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    // Tout ce qui n'est pas alphanumérique devient une césure…
    .replace(/[^a-z0-9]+/g, '-')
    // …dont on ne garde qu'une seule, sans bord.
    .replace(/^-+|-+$/g, '')
    .slice(0, SLUG_MAX)
    // La troncature peut laisser un tiret final.
    .replace(/-+$/, '')
}

/**
 * Slug d'une action d'hyperviseur tel qu'il sera ENREGISTRÉ : préfixé par le
 * type, sans redoubler le préfixe. Même règle que `qualify_action_slug` côté
 * backend — deux types peuvent proposer un « reboot » sans se confondre.
 */
export function qualifierSlugAction(typeName: string, slug: string): string {
  const prefixe = `${typeName}-`
  return slug.startsWith(prefixe) ? slug : prefixe + slug
}
