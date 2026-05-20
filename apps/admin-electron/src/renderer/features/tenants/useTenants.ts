import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CreateChildTenantPayload, Tenant, UpdateTenantPayload } from "@shared/types";
import { api } from "@renderer/lib/api";

const KEY = ["tenants", "list"] as const;

export function useTenants() {
  return useQuery<Tenant[]>({ queryKey: KEY, queryFn: () => api.tenants.list() });
}

export function useCreateChildTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: CreateChildTenantPayload) => api.tenants.createChild(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateTenant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; payload: UpdateTenantPayload }) =>
      api.tenants.update(v.id, v.payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useSetTenantActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; active: boolean }) =>
      v.active ? api.tenants.activate(v.id) : api.tenants.deactivate(v.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
