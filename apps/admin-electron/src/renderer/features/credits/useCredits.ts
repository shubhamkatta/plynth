import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  CreditLedgerRow,
  CreditWallet,
  GrantCreditPayload,
} from "@shared/types";
import { api } from "@renderer/lib/api";

const WALLETS_KEY = ["credits", "wallets"] as const;
const LEDGER_KEY  = ["credits", "ledger"] as const;

export function useWallets() {
  return useQuery<CreditWallet[]>({
    queryKey: WALLETS_KEY,
    queryFn:  () => api.credits.wallets(),
  });
}

export function useLedger(limit: number) {
  return useQuery<CreditLedgerRow[]>({
    queryKey: [...LEDGER_KEY, limit],
    queryFn:  () => api.credits.ledger(limit),
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
