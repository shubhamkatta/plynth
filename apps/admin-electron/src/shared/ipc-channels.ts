// Single source of truth for IPC channel names. Imported by both the
// preload bridge and the main-process handlers so a typo in one place
// becomes a compile error in the other.

export const IPC = {
  auth: {
    loginAsUser:     "auth.loginAsUser",
    logout:          "auth.logout",
    getSession:      "auth.getSession",
    me:              "auth.me",
    setAdminToken:   "auth.setAdminToken",
    hasAdminToken:   "auth.hasAdminToken",
    clearAdminToken: "auth.clearAdminToken",
  },
  products: {
    list:   "products.list",
    create: "products.create",
  },
  tenants: {
    list:       "tenants.list",
    createChild:"tenants.createChild",
    update:     "tenants.update",
    activate:   "tenants.activate",
    deactivate: "tenants.deactivate",
  },
  users: {
    list:       "users.list",
    invite:     "users.invite",
    update:     "users.update",
    activate:   "users.activate",
    deactivate: "users.deactivate",
    remove:     "users.remove",
  },
  plans: {
    list:   "plans.list",
    create: "plans.create",
    update: "plans.update",
  },
  roles: {
    list:        "roles.list",
    create:      "roles.create",
    update:      "roles.update",
    assign:      "roles.assign",
    permissions: "roles.permissions",
  },
  subscriptions: {
    get:      "subscriptions.get",
    purchase: "subscriptions.purchase",
    change:   "subscriptions.change",
    cancel:   "subscriptions.cancel",
  },
  credits: {
    wallets: "credits.wallets",
    ledger:  "credits.ledger",
    grant:   "credits.grant",
  },
  audit: {
    list: "audit.list",
  },
  system: {
    baseUrl:             "system.baseUrl",
    setBaseUrl:          "system.setBaseUrl",
    openExternal:        "system.openExternal",
    adminProductSlug:    "system.adminProductSlug",
    setAdminProductSlug: "system.setAdminProductSlug",
    actingTenantSlug:    "system.actingTenantSlug",
    setActingTenantSlug: "system.setActingTenantSlug",
  },
} as const;
