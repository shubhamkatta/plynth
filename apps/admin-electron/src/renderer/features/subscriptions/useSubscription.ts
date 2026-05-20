import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  CancelSubscriptionPayload,
  ChangeSubscriptionPayload,
  Plan,
  PurchaseSubscriptionPayload,
  Subscription,
} from "@shared/types";
import { api, isApiError } from "@renderer/lib/api";

const KEY       = ["subscription"] as const;
const PLANS_KEY = ["plans", "list"] as const;

export function useSubscription() {
  return useQuery<Subscription | null>({
    queryKey: KEY,
    queryFn: async () => {
      try {
        return await api.subscriptions.get();
      } catch (e) {
        if (isApiError(e) && e.status === 404) return null;
        throw e;
      }
    },
  });
}

export function usePlans() {
  return useQuery<Plan[]>({
    queryKey: PLANS_KEY,
    queryFn:  () => api.plans.list(),
  });
}

export function usePurchaseSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: PurchaseSubscriptionPayload) => api.subscriptions.purchase(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useChangeSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: ChangeSubscriptionPayload) => api.subscriptions.change(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useCancelSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: CancelSubscriptionPayload) => api.subscriptions.cancel(p),
    onSuccess:  () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
