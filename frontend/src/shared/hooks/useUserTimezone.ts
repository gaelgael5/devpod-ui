import { useUserPreferences } from './useUserPreferences'

// Clé de préférence du fuseau horaire d'affichage. Valeur = identifiant IANA
// (« Europe/Paris ») ou '' = fuseau du navigateur.
export const TIMEZONE_PREF_KEY = 'ui.timezone'

/** Liste des fuseaux IANA proposés (Intl si dispo, sinon repli raisonnable). */
export function supportedTimezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  if (typeof intl.supportedValuesOf === 'function') {
    try {
      return intl.supportedValuesOf('timeZone')
    } catch {
      /* repli ci-dessous */
    }
  }
  return [
    'UTC',
    'Europe/Paris',
    'Europe/London',
    'America/New_York',
    'America/Los_Angeles',
    'Asia/Tokyo',
    'Australia/Sydney',
  ]
}

/** Fuseau du navigateur (défaut si aucune préférence). */
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/** Fuseau d'affichage choisi par l'utilisateur, ou undefined (= navigateur). */
export function useUserTimezone(): string | undefined {
  const { data } = useUserPreferences()
  const tz = data?.[TIMEZONE_PREF_KEY]
  return typeof tz === 'string' && tz ? tz : undefined
}

/** Formate un instant ISO dans le fuseau donné (undefined = fuseau du navigateur). */
export function formatInstant(iso: string, timeZone?: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return d.toLocaleString(undefined, timeZone ? { timeZone } : undefined)
  } catch {
    return d.toLocaleString()
  }
}
