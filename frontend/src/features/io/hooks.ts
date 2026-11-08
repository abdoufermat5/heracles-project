import { useMutation, useQuery } from '@tanstack/react-query'
import { ioApi } from './api'

export function useIoAccess() {
  return useQuery({
    queryKey: ['io', 'access'],
    queryFn: ioApi.access,
    staleTime: 60_000,
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
