import { useMutation, useQuery } from '@tanstack/react-query'
import { isApiError } from '@/api/client'
import { useCapabilities } from '@/features/admin/hooks'
import { ioApi, type IoAccess } from './api'

const NO_ACCESS: IoAccess = { ldif_export: false, ldif_import: false, csv_import: false }

/**
 * Rights on the import / export tools.
 *
 * The capabilities already say whether the plugin is available: when it is not, the answer
 * is "no access" and nothing is requested. Servers older than that flag are probed; they
 * answer 404 while the plugin is off, which still means no access.
 */
export function useIoAccess() {
  const caps = useCapabilities()
  const knownAbsent = caps.data?.io === false
  // A server older than the flag has no `io` field: probe it, its 404 still means no access.
  const enabled = caps.isError || (caps.data !== undefined && caps.data.io !== false)

  const query = useQuery({
    queryKey: ['io', 'access'],
    queryFn: async (): Promise<IoAccess> => {
      try {
        return await ioApi.access()
      } catch (e) {
        if (isApiError(e) && e.status === 404) return NO_ACCESS
        throw e
      }
    },
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  })

  return {
    ...query,
    data: knownAbsent ? NO_ACCESS : query.data,
    isPending: knownAbsent ? false : enabled ? query.isPending : true,
    isError: enabled && query.isError,
    error: enabled ? query.error : null,
  }
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
