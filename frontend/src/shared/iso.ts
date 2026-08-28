/**
 * Référentiels ISO pour la saisie : pays (3166-1 alpha-2) et devises (4217).
 *
 * Les libellés viennent d'`Intl.DisplayNames`, donc traduits par le navigateur
 * dans la langue de l'utilisateur : pas de table de traductions à maintenir, et
 * pas de « Germany » affiché à un francophone.
 *
 * Le portail stocke le CODE, jamais le libellé — celui-ci n'est qu'une aide à la
 * lecture, et il change avec la langue.
 */

/**
 * Codes pays ISO-3166-1 **alpha-2**, le format qu'exige le serveur
 * (`^[A-Z]{2}$`). `Intl.supportedValuesOf` ne sait pas énumérer les régions :
 * la liste est donc statique, et c'est la seule façon honnête de l'avoir
 * complète hors ligne.
 */
const CODES_PAYS = [
  'AD', 'AE', 'AF', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AT', 'AU', 'AW', 'AX', 'AZ',
  'BA', 'BB', 'BD', 'BE', 'BF', 'BG', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS',
  'BT', 'BV', 'BW', 'BY', 'BZ', 'CA', 'CC', 'CD', 'CF', 'CG', 'CH', 'CI', 'CK', 'CL', 'CM', 'CN',
  'CO', 'CR', 'CU', 'CV', 'CW', 'CX', 'CY', 'CZ', 'DE', 'DJ', 'DK', 'DM', 'DO', 'DZ', 'EC', 'EE',
  'EG', 'EH', 'ER', 'ES', 'ET', 'FI', 'FJ', 'FK', 'FM', 'FO', 'FR', 'GA', 'GB', 'GD', 'GE', 'GF',
  'GG', 'GH', 'GI', 'GL', 'GM', 'GN', 'GP', 'GQ', 'GR', 'GS', 'GT', 'GU', 'GW', 'GY', 'HK', 'HM',
  'HN', 'HR', 'HT', 'HU', 'ID', 'IE', 'IL', 'IM', 'IN', 'IO', 'IQ', 'IR', 'IS', 'IT', 'JE', 'JM',
  'JO', 'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KP', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC',
  'LI', 'LK', 'LR', 'LS', 'LT', 'LU', 'LV', 'LY', 'MA', 'MC', 'MD', 'ME', 'MF', 'MG', 'MH', 'MK',
  'ML', 'MM', 'MN', 'MO', 'MP', 'MQ', 'MR', 'MS', 'MT', 'MU', 'MV', 'MW', 'MX', 'MY', 'MZ', 'NA',
  'NC', 'NE', 'NF', 'NG', 'NI', 'NL', 'NO', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA', 'PE', 'PF', 'PG',
  'PH', 'PK', 'PL', 'PM', 'PN', 'PR', 'PS', 'PT', 'PW', 'PY', 'QA', 'RE', 'RO', 'RS', 'RU', 'RW',
  'SA', 'SB', 'SC', 'SD', 'SE', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS',
  'ST', 'SV', 'SX', 'SY', 'SZ', 'TC', 'TD', 'TF', 'TG', 'TH', 'TJ', 'TK', 'TL', 'TM', 'TN', 'TO',
  'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY', 'UZ', 'VA', 'VC', 'VE', 'VG', 'VI',
  'VN', 'VU', 'WF', 'WS', 'YE', 'YT', 'ZA', 'ZM', 'ZW',
] as const

/** Devises servant de repli si le navigateur ne sait pas les énumérer. */
const DEVISES_REPLI = [
  'AUD', 'BRL', 'CAD', 'CHF', 'CNY', 'DKK', 'EUR', 'GBP', 'HKD', 'ILS', 'INR', 'JPY', 'KRW',
  'MAD', 'MXN', 'NOK', 'NZD', 'PLN', 'RON', 'SEK', 'SGD', 'TND', 'TRY', 'USD', 'ZAR',
]

export interface OptionIso {
  code: string
  /** Libellé traduit, ou le code lui-même si le navigateur ne sait pas le nommer. */
  label: string
}

function nommeur(langue: string, type: 'region' | 'currency'): (code: string) => string {
  try {
    const dn = new Intl.DisplayNames([langue], { type })
    return (code) => dn.of(code) ?? code
  } catch {
    // Navigateur sans Intl.DisplayNames : le code reste lisible, la saisie reste
    // possible. On n'empêche pas de travailler pour un confort d'affichage.
    return (code) => code
  }
}

function trier(options: OptionIso[], langue: string): OptionIso[] {
  return [...options].sort((a, b) => a.label.localeCompare(b.label, langue))
}

/** Pays ISO-3166-1 alpha-2, triés par libellé dans la langue donnée. */
export function paysIso(langue: string): OptionIso[] {
  const nomme = nommeur(langue, 'region')
  return trier(
    CODES_PAYS.map((code) => ({ code, label: nomme(code) })),
    langue,
  )
}

/** Devises ISO-4217 connues du navigateur, triées par libellé. */
export function devisesIso(langue: string): OptionIso[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  let codes = DEVISES_REPLI
  if (typeof intl.supportedValuesOf === 'function') {
    try {
      codes = intl.supportedValuesOf('currency')
    } catch {
      codes = DEVISES_REPLI
    }
  }
  const nomme = nommeur(langue, 'currency')
  return trier(
    codes.map((code) => ({ code, label: nomme(code) })),
    langue,
  )
}
