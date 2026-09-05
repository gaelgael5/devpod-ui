import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import en from './en.json'
import fr from './fr.json'

export const i18nReady = i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, fr: { translation: fr } },
    fallbackLng: 'en',
    supportedLngs: ['en', 'fr'],
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'i18nextLng',
    },
  })

export default i18n

// `<html lang>` suit la langue courante. Sur une page publique ce n'est pas
// cosmétique : les moteurs d'indexation et les lecteurs d'écran s'y fient.
function synchroniserLangDocument(langue: string): void {
  if (typeof document !== 'undefined') document.documentElement.lang = langue.split('-')[0]
}

void i18nReady.then(() => synchroniserLangDocument(i18n.language))
i18n.on('languageChanged', synchroniserLangDocument)
