import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type {
  CreditLedgerRow,
  CreditWallet,
  GrantCreditPayload,
} from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerCreditHandlers(): void {
  ipcMain.handle(IPC.credits.wallets, () =>
    run<CreditWallet[]>(async () =>
      call<CreditWallet[]>("GET", "/api/v1/credits/wallets"),
    ),
  );

  ipcMain.handle(IPC.credits.ledger, (_e, limit?: number) =>
    run<CreditLedgerRow[]>(async () => {
      const clamped = Math.min(Math.max(limit ?? 100, 1), 500);
      return call<CreditLedgerRow[]>(
        "GET",
        `/api/v1/credits/ledger?limit=${clamped}`,
      );
    }),
  );

  ipcMain.handle(IPC.credits.grant, (_e, payload: GrantCreditPayload) =>
    run<CreditWallet>(async () =>
      call<CreditWallet>("POST", "/api/v1/credits/grant", {
        body:       payload,
        idempotent: true,
      }),
    ),
  );
}
