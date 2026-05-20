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
  signIn:              (s: UserSession) => void;
  signOut:             ()              => void;
  setAdminToken:       (v: boolean)    => void;
  setAdminProductSlug: (slug: string | null) => Promise<void>;
  refreshAdminToken:   ()              => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  session:          null,
  loading:          true,
  hasAdminToken:    false,
  adminProductSlug: null,
  signIn:           (session)        => set({ session }),
  signOut:          ()               => set({ session: null }),
  setAdminToken:    (hasAdminToken)  => set({ hasAdminToken }),
  setAdminProductSlug: async (slug) => {
    await api.system.setAdminProductSlug(slug);
    set({ adminProductSlug: slug });
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
        const [session, hasAdminToken, adminProductSlug] = await Promise.all([
          api.auth.getSession(),
          api.auth.hasAdminToken(),
          api.system.adminProductSlug(),
        ]);
        useAuthStore.setState({ session, hasAdminToken, adminProductSlug, loading: false });
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
 *  session, OR the platform admin token with a product context selected. */
export function useEffectiveAuth(): {
  isAuthed: boolean;
  reason:   string | null;   // null when authed; explains *why* when not.
} {
  const { session, hasAdminToken, adminProductSlug } = useAuthStore();
  if (session) return { isAuthed: true, reason: null };
  if (hasAdminToken) {
    return adminProductSlug
      ? { isAuthed: true, reason: null }
      : { isAuthed: false, reason: "Pick a product context in the header dropdown to manage it." };
  }
  return { isAuthed: false, reason: "Sign in via the User or Platform Admin tab." };
}
