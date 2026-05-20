import { ipcMain } from "electron";

import { IPC } from "@shared/ipc-channels";
import type { AuditEntry, AuditQuery } from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";

export function registerAuditHandlers(): void {
  ipcMain.handle(IPC.audit.list, (_e, query: AuditQuery) =>
    run<AuditEntry[]>(async () => {
      // Platform doesn't yet expose /audit; until then, surface
      // /credits/ledger as a stand-in for the demo. When the real
      // endpoint lands (planned in ARCHITECTURE.md), swap this path.
      const limit = Math.min(Math.max(query.limit ?? 100, 1), 500);
      // TEMP: read from credits ledger as a stand-in until /audit ships
      return call<AuditEntry[]>("GET", `/api/v1/credits/ledger?limit=${limit}`);
    }),
  );
}
