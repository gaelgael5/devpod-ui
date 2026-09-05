import { useTranslation } from 'react-i18next'
import { CULTURES, useSetCulture, type Culture } from '@/features/profile/useCulture'

/**
 * Changer la langue de l'interface, avec ou sans compte.
 *
 * Deux modes, une seule règle de changement — pour qu'il n'existe pas deux
 * façons de changer de langue qui divergeraient à la troisième langue ajoutée :
 *
 * - `persist: false` — visiteur anonyme. Seul i18next agit, et son cache
 *   `localStorage` retient le choix. **Aucun appel réseau** : `/me/config` est
 *   authentifié et rendrait un 401 sur une page publique, ce qui déclencherait
 *   la redirection globale vers la connexion.
 * - `persist: true` — utilisateur connecté. Le choix va AUSSI en base, parce que
 *   la culture sert au-delà de l'écran : elle choisit le gabarit des messages
 *   qui lui sont envoyés (cf. `useCulture`).
 */
export function useLanguageChoice({ persist }: { persist: boolean }) {
  const { i18n } = useTranslation()
  const setCulture = useSetCulture()

  // Repli aligne sur le `fallbackLng` d'i18next : une langue inconnue de
  // CULTURES (variante regionale, valeur heritee du localStorage) doit rendre
  // le meme choix que celui qu'i18next affichera reellement.
  const prefixe = i18n.language.split('-')[0]
  const current: Culture = (CULTURES as readonly string[]).includes(prefixe)
    ? (prefixe as Culture)
    : 'en'

  function choose(langue: Culture) {
    if (persist) {
      // La base fait foi. `useSetCulture` applique la langue a l'ecran dans son
      // `onSuccess`, une fois le serveur d'accord. L'appliquer AVANT laisserait,
      // si le PUT echoue, un ecran dans une langue que le compte n'a pas — et
      // i18next aurait deja ecrit ce mauvais choix dans le localStorage, que le
      // detecteur relira au prochain chargement.
      setCulture.mutate(langue)
      return
    }
    // Anonyme : aucun compte ou ranger le choix, le cache i18next fait foi.
    void i18n.changeLanguage(langue)
  }

  return { current, available: CULTURES, choose }
}
