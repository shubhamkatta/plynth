import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AssignRolePayload,
  CreateRolePayload,
  Role,
  UpdateRolePayload,
} from "@shared/types";
import { api } from "@renderer/lib/api";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";

const LIST_KEY        = ["roles", "list"] as const;
const PERMISSIONS_KEY = ["roles", "permissions"] as const;

export function useRoles() {
  const { isAuthed } = useEffectiveAuth();
  return useQuery<Role[]>({
    queryKey: LIST_KEY,
    queryFn:  () => api.roles.list(),
    enabled:  isAuthed,
  });
}

export function usePermissions() {
  const { isAuthed } = useEffectiveAuth();
  return useQuery<string[]>({
    queryKey: PERMISSIONS_KEY,
    queryFn:  () => api.roles.permissions(),
    enabled:  isAuthed,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: CreateRolePayload) => api.roles.create(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: LIST_KEY }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; payload: UpdateRolePayload }) =>
      api.roles.update(v.id, v.payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: LIST_KEY }),
  });
}

export function useAssignRole() {
  return useMutation({
    mutationFn: (p: AssignRolePayload) => api.roles.assign(p),
  });
}
