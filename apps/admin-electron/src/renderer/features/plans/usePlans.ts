import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CreatePlanPayload, Plan, UpdatePlanPayload } from "@shared/types";
import { api } from "@renderer/lib/api";

const KEY = ["plans", "list"] as const;

export function usePlans() {
  return useQuery<Plan[]>({ queryKey: KEY, queryFn: () => api.plans.list() });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: CreatePlanPayload) => api.plans.create(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useUpdatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { code: string; payload: UpdatePlanPayload }) =>
      api.plans.update(v.code, v.payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
