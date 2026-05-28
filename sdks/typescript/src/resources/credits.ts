import type { HttpClient } from "../http.js";
import type {
  ConsumeCreditsRequest,
  CreditLedgerEntry,
  CreditWallet,
  GrantCreditsRequest,
} from "../types.js";

export class CreditsResource {
  constructor(private readonly http: HttpClient) {}

  async wallets(): Promise<CreditWallet[]> {
    return this.http.request<CreditWallet[]>({
      method: "GET",
      path: "/api/v1/credits/wallets",
    });
  }

  async ledger(opts: { limit?: number; cursor?: string } = {}): Promise<CreditLedgerEntry[]> {
    return this.http.request<CreditLedgerEntry[]>({
      method: "GET",
      path: "/api/v1/credits/ledger",
      query: { limit: opts.limit, cursor: opts.cursor },
    });
  }

  async consume(req: ConsumeCreditsRequest): Promise<CreditWallet> {
    return this.http.request<CreditWallet>({
      method: "POST",
      path: "/api/v1/credits/consume",
      body: req,
      idempotent: true,
    });
  }

  async grant(req: GrantCreditsRequest): Promise<CreditWallet> {
    return this.http.request<CreditWallet>({
      method: "POST",
      path: "/api/v1/credits/grant",
      body: req,
      idempotent: true,
    });
  }
}
