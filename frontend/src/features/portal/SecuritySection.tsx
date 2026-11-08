import { KeyRound, ShieldCheck, Smartphone } from 'lucide-react'
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

      {/* Guided setup steps */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex items-start gap-3 rounded-lg border bg-card p-3.5 shadow-2xs">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
            <Smartphone className="size-4" aria-hidden />
          </div>
          <div className="space-y-0.5">
            <h3 className="text-small font-semibold text-foreground">
              Step 1: {t('settingsUI.portal.stepTotp')}
            </h3>
            <p className="text-caption text-muted-foreground">
              Use Google Authenticator, 1Password, or any standard authenticator app to generate one-time codes.
            </p>
          </div>
        </div>

        <div className="flex items-start gap-3 rounded-lg border bg-card p-3.5 shadow-2xs">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
            <KeyRound className="size-4" aria-hidden />
          </div>
          <div className="space-y-0.5">
            <h3 className="text-small font-semibold text-foreground">
              Step 2: {t('settingsUI.portal.stepKeys')}
            </h3>
            <p className="text-caption text-muted-foreground">
              Register a hardware security key (YubiKey, passkey, or device biometric) for seamless sign-in.
            </p>
          </div>
        </div>
      </div>

      {/* Existing panels for 2FA and Security Keys */}
      <div className="grid gap-4 lg:grid-cols-2">
        <TwoFactorPanel />
        <SecurityKeysPanel />
      </div>
    </section>
  )
}
