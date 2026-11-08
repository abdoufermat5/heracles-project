import { FileText, FileUp, ImageUp, Trash2, UploadCloud, User } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
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
      let { width, height } = img
      if (width <= maxW && height <= maxH) return resolve(dataUrl)
      const ratio = Math.min(maxW / width, maxH / height)
      width = Math.round(width * ratio)
      height = Math.round(height * ratio)
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
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
  const [isDragOver, setIsDragOver] = useState(false)
  const src = typeof p.value === 'string' && p.value ? p.value : null
  const max = p.descriptor.image ?? { max_width: 200, max_height: 200 }

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const url = await readAsDataUrl(file)
    p.onChange(await fitImage(url, max.max_width, max.max_height))
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (p.readOnly) return
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) {
      void onFile(file)
    }
  }

  if (p.readOnly) {
    return (
      <div className="flex items-center gap-3">
        <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted">
          {src ? (
            <img src={src} alt={p.descriptor.label} className="size-full object-cover" />
          ) : (
            <User className="text-muted-foreground size-6" aria-hidden />
          )}
        </div>
        {!src && <span className="text-[13px] text-muted-foreground">—</span>}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div
        className={cn(
          'relative flex size-16 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-md border border-dashed bg-muted/30 transition-colors',
          isDragOver
            ? 'border-signal bg-primary-soft/40'
            : 'border-border hover:border-signal/50',
        )}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => input.current?.click()}
        title={t('fields.upload')}
      >
        {src ? (
          <img src={src} alt={p.descriptor.label} className="size-full object-cover" />
        ) : (
          <div className="flex flex-col items-center gap-1 text-center">
            {isDragOver ? (
              <UploadCloud className="size-5 text-signal" />
            ) : (
              <User className="text-muted-foreground size-6" aria-hidden />
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <input
          ref={input}
          id={p.id}
          type="file"
          accept="image/*"
          className="sr-only"
          data-testid={`${p.id}-input`}
          onChange={(e) => void onFile(e.target.files?.[0])}
        />
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 gap-1.5"
            onClick={() => input.current?.click()}
          >
            <ImageUp className="size-3.5" />
            {t('fields.upload')}
          </Button>
          {src && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive h-8 gap-1.5"
              onClick={() => p.onChange(null)}
            >
              <Trash2 className="size-3.5" />
              {t('fields.remove')}
            </Button>
          )}
        </div>
        <p className="text-[12px] text-muted-foreground">
          {t('fields.dragDropImage', 'Drag and drop an image or click to browse.')}
        </p>
      </div>
    </div>
  )
}

export function FileField({ p }: { p: FieldInputProps }) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const has = typeof p.value === 'string' && p.value !== ''
  const size = has ? Math.round(((p.value as string).length * 3) / 4 / 1024) : 0

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const url = await readAsDataUrl(file)
    p.onChange(url.slice(url.indexOf(',') + 1)) // plain base64 per contract
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (p.readOnly) return
    const file = e.dataTransfer.files[0]
    if (file) void onFile(file)
  }

  if (p.readOnly) {
    return (
      <div className="flex h-8 items-center gap-2 text-[13px]">
        {has ? (
          <>
            <FileText className="size-4 text-muted-foreground" />
            <Badge variant="secondary" className="font-mono text-xs">
              {t('fields.fileStored', { size })}
            </Badge>
          </>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </div>
    )
  }

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-3 rounded-md border p-2.5 transition-colors',
        isDragOver
          ? 'border-signal bg-primary-soft/30'
          : 'border-border bg-muted/20',
      )}
      onDragOver={(e) => {
        e.preventDefault()
        setIsDragOver(true)
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      <input
        ref={input}
        id={p.id}
        type="file"
        className="sr-only"
        data-testid={`${p.id}-input`}
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <FileText className="text-muted-foreground size-4 shrink-0" />
        <span className="truncate text-[13px] text-muted-foreground">
          {has ? t('fields.fileStored', { size }) : t('fields.noFile')}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
          onClick={() => input.current?.click()}
        >
          <FileUp className="size-3.5" />
          {t('fields.upload')}
        </Button>
        {has && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive h-8 gap-1.5"
            onClick={() => p.onChange(null)}
          >
            <Trash2 className="size-3.5" />
            {t('fields.remove')}
          </Button>
        )}
      </div>
    </div>
  )
}
