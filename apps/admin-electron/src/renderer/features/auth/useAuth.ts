import { create } from "zustand";
import { useEffect } from "react";
import type { UserSession } from "@shared/types";
import { api } from "@renderer/lib/api";

interface AuthState {
  session:             UserSession | null;
  loading:             boolean;
  hasAdminToken:       boolean;
  /** When operating in admin-only mode (no JWT session, just the platform
   *  admin token), this slug pins every tenant-scoped call to a product. */
  adminProductSlug:    string | null;
  /** Active acting-tenant slug. When set, the main process auto-injects
   *  `X-Acting-Tenant-Slug` on every call so every tenant-scoped page
   *  operates inside that child tenant. */
  actingTenantSlug:    string | null;
  signIn:              (s: UserSession) => void;
  signOut:             ()              => void;
  setAdminToken:       (v: boolean)    => void;
  setAdminProductSlug: (slug: string | null) => Promise<void>;
  setActingTenantSlug: (slug: string | null) => Promise<void>;
  refreshAdminToken:   ()              => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  session:          null,
  loading:          true,
  hasAdminToken:    false,
  adminProductSlug: null,
  actingTenantSlug: null,
  signIn:           (session)        => set({ session }),
  signOut:          ()               => set({ session: null }),
  setAdminToken:    (hasAdminToken)  => set({ hasAdminToken }),
  setAdminProductSlug: async (slug) => {
    await api.system.setAdminProductSlug(slug);
    // Switching products auto-clears acting tenant (the slug doesn't
    // exist in the new product). The IPC handler does the same on disk.
    set({ adminProductSlug: slug, actingTenantSlug: null });
  },
  setActingTenantSlug: async (slug) => {
    await api.system.setActingTenantSlug(slug);
    set({ actingTenantSlug: slug });
  },
  refreshAdminToken: async () => {
    try {
      const v = await api.auth.hasAdminToken();
      set({ hasAdminToken: v });
    } catch {
      set({ hasAdminToken: false });
    }
  },
}));

/** Mount once at the app root — hydrates session + admin-token + admin
 *  product context from the main process. */
export function useAuthBootstrap() {
  useEffect(() => {
    void (async () => {
      try {
        const [session, hasAdminToken, adminProductSlug, actingTenantSlug] = await Promise.all([
          api.auth.getSession(),
          api.auth.hasAdminToken(),
          api.system.adminProductSlug(),
          api.system.actingTenantSlug(),
        ]);
        useAuthStore.setState({
          session, hasAdminToken, adminProductSlug, actingTenantSlug,
          loading: false,
        });
      } catch {
        useAuthStore.setState({ loading: false });
      }
    })();
  }, []);
}

export function useAuth() {
  return useAuthStore();
}

/** Effective authentication for tenant-scoped pages: either a real user
 *  session, OR the platform admin token with a product context selected.
 *  Uses individual selectors (not the whole-store form) so Vite HMR doesn't
 *  invalidate the store reference between renders. */
export function useEffectiveAuth(): {
  isAuthed: boolean;
  reason:   string | null;   // null when authed; explains *why* when not.
} {
  const session          = useAuthStore(s => s.session);
  const hasAdminToken    = useAuthStore(s => s.hasAdminToken);
  const adminProductSlug = useAuthStore(s => s.adminProductSlug);
  if (session) return { isAuthed: true, reason: null };
  if (hasAdminToken) {
    return adminProductSlug
      ? { isAuthed: true, reason: null }
      : { isAuthed: false, reason: "Pick a product context in the header dropdown to manage it." };
  }
  return { isAuthed: false, reason: "Sign in via the User or Platform Admin tab." };
}
