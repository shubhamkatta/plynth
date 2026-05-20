import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { InviteUserPayload, PlatformUser, UpdateUserPayload } from "@shared/types";
import { api } from "@renderer/lib/api";

const KEY = ["users", "list"] as const;

export function useUsers() {
  return useQuery<PlatformUser[]>({ queryKey: KEY, queryFn: () => api.users.list() });
}

export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: InviteUserPayload) => api.users.invite(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; payload: UpdateUserPayload }) =>
      api.users.update(v.id, v.payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useSetUserActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; active: boolean }) =>
      v.active ? api.users.activate(v.id) : api.users.deactivate(v.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRemoveUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.users.remove(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
