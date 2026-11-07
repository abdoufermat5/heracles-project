import { FileUp, ImageUp, Trash2, User } from 'lucide-react'
import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import type { FieldInputProps } from './types'

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result))
    r.onerror = () => reject(r.error ?? new Error('read failed'))
    r.readAsDataURL(file)
  })
}

/** Downscale to fit max dimensions (best effort; falls back to the original). */
async function fitImage(dataUrl: string, maxW: number, maxH: number): Promise<string> {
  if (typeof Image === 'undefined' || typeof document === 'undefined') return dataUrl
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const ratio = Math.min(1, maxW / img.width, maxH / img.height)
      if (ratio >= 1 || !img.width) return resolve(dataUrl)
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(img.width * ratio)
      canvas.height = Math.round(img.height * ratio)
      const ctx = canvas.getContext('2d')
      if (!ctx) return resolve(dataUrl)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      resolve(canvas.toDataURL('image/jpeg', 0.9))
    }
    img.onerror = () => resolve(dataUrl)
    img.src = dataUrl
  })
}

export function ImageField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const src = typeof p.value === 'string' && p.value ? p.value : null
  const max = p.descriptor.image ?? { max_width: 200, max_height: 200 }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const url = await readAsDataUrl(file)
    p.onChange(await fitImage(url, max.max_width, max.max_height))
  }

  return (
    <div className="flex items-center gap-4">
      <div className="bg-muted flex size-20 items-center justify-center overflow-hidden rounded-lg border">
        {src ? (
          <img src={src} alt={p.descriptor.label} className="size-full object-cover" />
        ) : (
          <User className="text-muted-foreground size-8" aria-hidden />
        )}
      </div>
      {!p.readOnly && (
        <div className="flex gap-2">
          <input
            ref={input}
            id={p.id}
            type="file"
            accept="image/*"
            className="sr-only"
            data-testid={`${p.id}-input`}
            onChange={(e) => void onFile(e.target.files?.[0])}
          />
          <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
            <ImageUp className="size-4" />
            {t('fields.upload')}
          </Button>
          {src && (
            <Button type="button" variant="ghost" size="sm" onClick={() => p.onChange(null)}>
              <Trash2 className="size-4" />
              {t('fields.remove')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

export function FileField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const has = typeof p.value === 'string' && p.value !== ''
  const size = has ? Math.round(((p.value as string).length * 3) / 4 / 1024) : 0

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const url = await readAsDataUrl(file)
    p.onChange(url.slice(url.indexOf(',') + 1)) // plain base64 per the contract
  }

  return (
    <div className="flex items-center gap-3">
      <input
        ref={input}
        id={p.id}
        type="file"
        className="sr-only"
        data-testid={`${p.id}-input`}
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <span className="text-muted-foreground text-sm">
        {has ? t('fields.fileStored', { size }) : t('fields.noFile')}
      </span>
      {!p.readOnly && (
        <>
          <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
            <FileUp className="size-4" />
            {t('fields.upload')}
          </Button>
          {has && (
            <Button type="button" variant="ghost" size="sm" onClick={() => p.onChange(null)}>
              <Trash2 className="size-4" />
              {t('fields.remove')}
            </Button>
          )}
        </>
      )}
    </div>
  )
}
