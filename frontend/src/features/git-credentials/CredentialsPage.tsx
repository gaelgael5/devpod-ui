import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import GitCredentialManager from './GitCredentialManager'
import VaultTab from '@/features/vault/VaultTab'
import CertificatesTab from '@/features/certificates/CertificatesTab'
import SecretsTab from '@/features/secrets/SecretsTab'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="vault" className="flex flex-col gap-4">
      <TabsList className="self-start">
        <TabsTrigger value="vault">{t('vault.tabLabel')}</TabsTrigger>
        <TabsTrigger value="certificates">{t('certificates.tabLabel')}</TabsTrigger>
        <TabsTrigger value="secrets">{t('secrets.tabLabel')}</TabsTrigger>
        <TabsTrigger value="git">{t('gitCredentials.title')}</TabsTrigger>
      </TabsList>
      <TabsContent value="vault" className="mt-0">
        <VaultTab />
      </TabsContent>
      <TabsContent value="certificates" className="mt-0">
        <CertificatesTab />
      </TabsContent>
      <TabsContent value="secrets" className="mt-0">
        <SecretsTab />
      </TabsContent>
      <TabsContent value="git" className="mt-0">
        <GitCredentialManager />
      </TabsContent>
    </Tabs>
  )
}
