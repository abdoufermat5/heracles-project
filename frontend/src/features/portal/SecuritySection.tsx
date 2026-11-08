import { ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SecurityKeysPanel } from '@/features/me/SecurityKeysPanel'
import { TwoFactorPanel } from '@/features/me/TwoFactorPanel'
export function SecuritySection() {
  const { t } = useTranslation()

  return (
    <section id="portal-security" className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-5 text-primary" aria-hidden />
          <h2 className="text-lead font-semibold tracking-tight text-foreground">
            {t('settingsUI.portal.securityTitle')}
          </h2>
        </div>
        <p className="text-body text-muted-foreground">
          {t('settingsUI.portal.securitySubtitle')}
        </p>
      </div>
      {/* Existing panels for 2FA and Security Keys */}
      <div className="grid gap-4 lg:grid-cols-2">
        <TwoFactorPanel />
        <SecurityKeysPanel />
      </div>
    </section>
  )
}
