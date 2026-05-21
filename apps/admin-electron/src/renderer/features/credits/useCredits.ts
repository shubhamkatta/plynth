import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  CreditLedgerRow,
  CreditWallet,
  GrantCreditPayload,
} from "@shared/types";
import { api } from "@renderer/lib/api";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";

const WALLETS_KEY = ["credits", "wallets"] as const;
const LEDGER_KEY  = ["credits", "ledger"] as const;

export function useWallets() {
  const { isAuthed } = useEffectiveAuth();
  return useQuery<CreditWallet[]>({
    queryKey: WALLETS_KEY,
    queryFn:  () => api.credits.wallets(),
    enabled:  isAuthed,
  });
}

export function useLedger(limit: number) {
  const { isAuthed } = useEffectiveAuth();
  return useQuery<CreditLedgerRow[]>({
    queryKey: [...LEDGER_KEY, limit],
    queryFn:  () => api.credits.ledger(limit),
    enabled:  isAuthed,
  });
}

export function useGrantCredits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: GrantCreditPayload) => api.credits.grant(p),
    onSuccess:  () => {
      void qc.invalidateQueries({ queryKey: WALLETS_KEY });
      void qc.invalidateQueries({ queryKey: LEDGER_KEY });
    },
  });
}
