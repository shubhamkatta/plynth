import { useEffect } from "react";
import { Center, Loader } from "@mantine/core";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { AppShellLayout } from "@renderer/components/AppShell";
import { useAuth, useAuthBootstrap } from "@renderer/features/auth/useAuth";
import { LoginPage } from "@renderer/features/auth/LoginPage";
import { DashboardPage } from "@renderer/features/dashboard/DashboardPage";
import { ProductsPage } from "@renderer/features/products/ProductsPage";
import { AuditPage } from "@renderer/features/audit/AuditPage";
import { SettingsPage } from "@renderer/features/settings/SettingsPage";
import { TenantsPage } from "@renderer/features/tenants/TenantsPage";
import { UsersPage } from "@renderer/features/users/UsersPage";
import { RolesPage } from "@renderer/features/roles/RolesPage";
import { PlansPage } from "@renderer/features/plans/PlansPage";
import { SubscriptionsPage } from "@renderer/features/subscriptions/SubscriptionsPage";
import { CreditsPage } from "@renderer/features/credits/CreditsPage";

export function App() {
  useAuthBootstrap();
  const { session, hasAdminToken, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  // Anyone with neither a user session nor a saved admin token must log in.
  const authed = Boolean(session) || hasAdminToken;

  useEffect(() => {
    if (loading) return;
    if (!authed && location.pathname !== "/login") {
      navigate("/login", { replace: true });
    } else if (authed && location.pathname === "/login") {
      navigate("/", { replace: true });
    }
  }, [authed, loading, location.pathname, navigate]);

  if (loading) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    );
  }

  if (!authed) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*"      element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <AppShellLayout>
      <Routes>
        <Route path="/"               element={<DashboardPage />} />
        <Route path="/products"       element={<ProductsPage />} />
        <Route path="/tenants"        element={<TenantsPage />} />
        <Route path="/users"          element={<UsersPage />} />
        <Route path="/roles"          element={<RolesPage />} />
        <Route path="/plans"          element={<PlansPage />} />
        <Route path="/subscriptions"  element={<SubscriptionsPage />} />
        <Route path="/credits"        element={<CreditsPage />} />
        <Route path="/audit"          element={<AuditPage />} />
        <Route path="/settings"       element={<SettingsPage />} />
        <Route path="*"               element={<Navigate to="/" replace />} />
      </Routes>
    </AppShellLayout>
  );
}
