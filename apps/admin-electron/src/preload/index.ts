// Preload script — the ONLY bridge between the sandboxed renderer and the
// privileged main process. Exposes a typed `window.api` surface via
// `contextBridge.exposeInMainWorld`. Anything not listed here is unreachable
// from the renderer, by design.

import { contextBridge, ipcRenderer } from "electron";

import { IPC } from "@shared/ipc-channels";
import type {
  BridgeApi,
  AssignRolePayload,
  AuditQuery,
  CancelSubscriptionPayload,
  ChangeSubscriptionPayload,
  CreateChildTenantPayload,
  CreatePlanPayload,
  CreateProductPayload,
  CreateRolePayload,
  GrantCreditPayload,
  InviteUserPayload,
  LoginInput,
  PurchaseSubscriptionPayload,
  UpdatePlanPayload,
  UpdateRolePayload,
  UpdateTenantPayload,
  UpdateUserPayload,
} from "@shared/types";

const invoke = <T>(channel: string, ...args: unknown[]) =>
  ipcRenderer.invoke(channel, ...args) as Promise<T>;

const api: BridgeApi = {
  auth: {
    loginAsUser:     (input: LoginInput) => invoke(IPC.auth.loginAsUser, input),
    logout:          ()                  => invoke(IPC.auth.logout),
    getSession:      ()                  => invoke(IPC.auth.getSession),
    me:              ()                  => invoke(IPC.auth.me),
    setAdminToken:   (token: string)     => invoke(IPC.auth.setAdminToken, token),
    hasAdminToken:   ()                  => invoke(IPC.auth.hasAdminToken),
    clearAdminToken: ()                  => invoke(IPC.auth.clearAdminToken),
  },
  products: {
    list:   ()                                => invoke(IPC.products.list),
    create: (payload: CreateProductPayload)   => invoke(IPC.products.create, payload),
  },
  tenants: {
    list:        ()                                            => invoke(IPC.tenants.list),
    createChild: (payload: CreateChildTenantPayload)           => invoke(IPC.tenants.createChild, payload),
    update:      (id: string, payload: UpdateTenantPayload)    => invoke(IPC.tenants.update, id, payload),
    activate:    (id: string)                                  => invoke(IPC.tenants.activate, id),
    deactivate:  (id: string)                                  => invoke(IPC.tenants.deactivate, id),
  },
  users: {
    list:        ()                                            => invoke(IPC.users.list),
    invite:      (payload: InviteUserPayload)                  => invoke(IPC.users.invite, payload),
    update:      (id: string, payload: UpdateUserPayload)      => invoke(IPC.users.update, id, payload),
    activate:    (id: string)                                  => invoke(IPC.users.activate, id),
    deactivate:  (id: string)                                  => invoke(IPC.users.deactivate, id),
    remove:      (id: string)                                  => invoke(IPC.users.remove, id),
  },
  plans: {
    list:    ()                                          => invoke(IPC.plans.list),
    create:  (payload: CreatePlanPayload)                => invoke(IPC.plans.create, payload),
    update:  (code: string, payload: UpdatePlanPayload)  => invoke(IPC.plans.update, code, payload),
  },
  roles: {
    list:        ()                                            => invoke(IPC.roles.list),
    create:      (payload: CreateRolePayload)                  => invoke(IPC.roles.create, payload),
    update:      (id: string, payload: UpdateRolePayload)      => invoke(IPC.roles.update, id, payload),
    assign:      (payload: AssignRolePayload)                  => invoke(IPC.roles.assign, payload),
    permissions: ()                                            => invoke(IPC.roles.permissions),
  },
  subscriptions: {
    get:      ()                                          => invoke(IPC.subscriptions.get),
    purchase: (payload: PurchaseSubscriptionPayload)      => invoke(IPC.subscriptions.purchase, payload),
    change:   (payload: ChangeSubscriptionPayload)        => invoke(IPC.subscriptions.change, payload),
    cancel:   (payload: CancelSubscriptionPayload)        => invoke(IPC.subscriptions.cancel, payload),
  },
  credits: {
    wallets: ()                                  => invoke(IPC.credits.wallets),
    ledger:  (limit?: number)                    => invoke(IPC.credits.ledger, limit),
    grant:   (payload: GrantCreditPayload)       => invoke(IPC.credits.grant, payload),
  },
  audit: {
    list:   (query: AuditQuery) => invoke(IPC.audit.list, query),
  },
  system: {
    baseUrl:             ()                       => invoke(IPC.system.baseUrl),
    setBaseUrl:          (url: string)            => invoke(IPC.system.setBaseUrl, url),
    openExternal:        (url: string)            => invoke(IPC.system.openExternal, url),
    adminProductSlug:    ()                       => invoke(IPC.system.adminProductSlug),
    setAdminProductSlug: (slug: string | null)    => invoke(IPC.system.setAdminProductSlug, slug),
    actingTenantSlug:    ()                       => invoke(IPC.system.actingTenantSlug),
    setActingTenantSlug: (slug: string | null)    => invoke(IPC.system.setActingTenantSlug, slug),
  },
};

try {
  contextBridge.exposeInMainWorld("api", api);
} catch (err) {
  // Should never happen in production — contextIsolation is enabled.
  console.error("preload.contextBridge_failed", err);
}
