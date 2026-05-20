import { ipcMain } from "electron";
import log from "electron-log/main";

import { IPC } from "@shared/ipc-channels";
import type { LoginInput, MeResponse, UserSession } from "@shared/types";
import { call } from "@main/api/client";
import { run } from "@main/api/errors";
import {
  clearAdminToken,
  clearSession,
  hasAdminToken,
  loadSession,
  saveAdminToken,
  saveSession,
} from "@main/api/secrets";

interface LoginResponse {
  access_token:  string;
  refresh_token: string;
  expires_at:    string;
}

export function registerAuthHandlers(): void {
  ipcMain.handle(IPC.auth.loginAsUser, (_e, input: LoginInput) =>
    run<UserSession>(async () => {
      const res = await call<LoginResponse>("POST", "/api/v1/auth/login", {
        skipAuth:    true,
        productSlug: input.productSlug,
        body: {
          email:       input.email,
          password:    input.password,
          tenant_slug: input.tenantSlug,
        },
      });
      const session: UserSession = {
        accessToken:  res.access_token,
        refreshToken: res.refresh_token,
        expiresAt:    res.expires_at,
        email:        input.email,
        productSlug:  input.productSlug,
      };
      await saveSession(session);
      log.info("auth.login_ok", { email: input.email, productSlug: input.productSlug });
      return session;
    }),
  );

  ipcMain.handle(IPC.auth.logout, () =>
    run<null>(async () => {
      const session = await loadSession();
      if (session) {
        try {
          await call("POST", "/api/v1/auth/logout", {
            body: { refresh_token: session.refreshToken, all_sessions: false },
          });
        } catch (err) {
          // Swallow — even if the server refuses, we want to drop local state.
          log.warn("auth.logout_server_call_failed", err);
        }
      }
      await clearSession();
      return null;
    }),
  );

  ipcMain.handle(IPC.auth.getSession, () =>
    run<UserSession | null>(async () => loadSession()),
  );

  ipcMain.handle(IPC.auth.me, () =>
    run<MeResponse>(async () => call<MeResponse>("GET", "/api/v1/auth/me")),
  );

  ipcMain.handle(IPC.auth.setAdminToken, (_e, token: string) =>
    run<null>(async () => { await saveAdminToken(token); return null; }),
  );

  ipcMain.handle(IPC.auth.hasAdminToken, () =>
    run<boolean>(async () => hasAdminToken()),
  );

  ipcMain.handle(IPC.auth.clearAdminToken, () =>
    run<null>(async () => { await clearAdminToken(); return null; }),
  );
}
