import { useTranslation } from 'react-i18next'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import GitCredentialManager from './GitCredentialManager'
import VaultTab from '@/features/vault/VaultTab'
import CertificatesTab from '@/features/certificates/CertificatesTab'
import SecretsTab from '@/features/secrets/SecretsTab'
import MCPTab from '@/features/mcp/MCPTab'
import SkillsTab from '@/features/skills/SkillsTab'

export default function CredentialsPage() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="vault" className="flex flex-col gap-4">
      {/* 6 onglets : barre scrollable horizontalement sur mobile (sinon débordement
          de la page). Sur desktop la pile tient et reste calée à gauche (w-max). */}
      <div className="-mx-3 overflow-x-auto px-3 sm:mx-0 sm:px-0">
        <TabsList className="w-max">
          <TabsTrigger value="vault">{t('vault.tabLabel')}</TabsTrigger>
          <TabsTrigger value="certificates">{t('certificates.tabLabel')}</TabsTrigger>
          <TabsTrigger value="secrets">{t('secrets.tabLabel')}</TabsTrigger>
          <TabsTrigger value="git">{t('gitCredentials.title')}</TabsTrigger>
          <TabsTrigger value="mcp">{t('mcp.tabLabel')}</TabsTrigger>
          <TabsTrigger value="skills">{t('skills.tabLabel')}</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="vault" className="mt-0"><VaultTab /></TabsContent>
      <TabsContent value="certificates" className="mt-0"><CertificatesTab /></TabsContent>
      <TabsContent value="secrets" className="mt-0"><SecretsTab /></TabsContent>
      <TabsContent value="git" className="mt-0"><GitCredentialManager /></TabsContent>
      <TabsContent value="mcp" className="mt-0"><MCPTab /></TabsContent>
      <TabsContent value="skills" className="mt-0"><SkillsTab /></TabsContent>
    </Tabs>
  )
}
