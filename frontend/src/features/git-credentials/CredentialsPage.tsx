import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import GitCredentialManager from './GitCredentialManager'
import VaultTab from '@/features/vault/VaultTab'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="git" className="flex flex-col gap-4">
      <TabsList className="self-start">
        <TabsTrigger value="git">{t('gitCredentials.title')}</TabsTrigger>
        <TabsTrigger value="vault">{t('vault.tabLabel')}</TabsTrigger>
      </TabsList>
      <TabsContent value="git" className="mt-0">
        <GitCredentialManager />
      </TabsContent>
      <TabsContent value="vault" className="mt-0">
        <VaultTab />
      </TabsContent>
    </Tabs>
  )
}
