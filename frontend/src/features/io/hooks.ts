import { useMutation, useQuery } from '@tanstack/react-query'
import { isApiError } from '@/api/client'
import { ioApi, type IoAccess } from './api'

const IO_ABSENT_KEY = 'heracles.io.absent'
const NO_ACCESS: IoAccess = { ldif_export: false, ldif_import: false, csv_import: false }

function ioKnownAbsent(): boolean {
  try {
    return sessionStorage.getItem(IO_ABSENT_KEY) === '1'
  } catch {
    return false
  }
}

/** Called when the import / export plugin is switched on or off. */
export function forgetIoAbsence(): void {
  try {
    sessionStorage.removeItem(IO_ABSENT_KEY)
  } catch {
    /* storage unavailable */
  }
}

/**
 * Rights on the import / export tools. The tools belong to a plugin: when it is off
 * the endpoint answers 404, which means "no access". The answer is remembered for the
 * browser session so pages do not ask again (and do not log a failed request each time).
 */
export function useIoAccess() {
  return useQuery({
    queryKey: ['io', 'access'],
    queryFn: async (): Promise<IoAccess> => {
      if (ioKnownAbsent()) return NO_ACCESS
      try {
        return await ioApi.access()
      } catch (e) {
        if (isApiError(e) && e.status === 404) {
          try {
            sessionStorage.setItem(IO_ABSENT_KEY, '1')
          } catch {
            /* storage unavailable */
          }
          return NO_ACCESS
        }
        throw e
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useCsvFields(type: string, template: string | null) {
  return useQuery({
    queryKey: ['io', 'csv-fields', type, template],
    queryFn: () => ioApi.csvFields(type, template),
    enabled: type !== '',
  })
}

export function useTemplates(type: string) {
  return useQuery({
    queryKey: ['io', 'templates', type],
    queryFn: () => ioApi.templates(type),
    enabled: type !== '',
    staleTime: 60_000,
  })
}

export function useLdifImport() {
  return useMutation({ mutationFn: ioApi.ldifImport })
}

export function useCsvParse() {
  return useMutation({ mutationFn: ioApi.csvParse })
}

export function useCsvImport(type: string) {
  return useMutation({
    mutationFn: (body: Parameters<typeof ioApi.csvImport>[1]) => ioApi.csvImport(type, body),
  })
}
