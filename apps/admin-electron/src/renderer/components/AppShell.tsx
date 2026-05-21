import {
  AppShell as MantineAppShell,
  Badge,
  Burger,
  Button,
  Group,
  NavLink,
  ScrollArea,
  Select,
  Text,
  Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  IconBoxMultiple,
  IconBuilding,
  IconCash,
  IconChartBar,
  IconCoin,
  IconCreditCard,
  IconHome,
  IconLogout,
  IconSettings,
  IconShield,
  IconUsers,
} from "@tabler/icons-react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { api } from "@renderer/lib/api";
import { notify } from "@renderer/lib/notify";
import { useAuth } from "@renderer/features/auth/useAuth";

interface NavItem {
  to:    string;
  label: string;
  icon:  React.ReactNode;
  status?: "ready" | "stub" | "admin";
}

const NAV: NavItem[] = [
  { to: "/",               label: "Dashboard",     icon: <IconHome size={18} />,        status: "ready" },
  { to: "/products",       label: "Products",      icon: <IconBoxMultiple size={18} />, status: "admin" },
  { to: "/tenants",        label: "Tenants",       icon: <IconBuilding size={18} />,    status: "ready" },
  { to: "/users",          label: "Users",         icon: <IconUsers size={18} />,       status: "ready" },
  { to: "/roles",          label: "Roles",         icon: <IconShield size={18} />,      status: "ready" },
  { to: "/plans",          label: "Plans",         icon: <IconCash size={18} />,        status: "ready" },
  { to: "/subscriptions",  label: "Subscriptions", icon: <IconCreditCard size={18} />,  status: "ready" },
  { to: "/credits",        label: "Credits",       icon: <IconCoin size={18} />,        status: "ready" },
  { to: "/audit",          label: "Audit",         icon: <IconChartBar size={18} />,    status: "ready" },
  { to: "/settings",       label: "Settings",      icon: <IconSettings size={18} />,    status: "ready" },
];

function AdminProductPicker() {
  const { hasAdminToken, session, adminProductSlug, setAdminProductSlug } = useAuth();
  const qc = useQueryClient();
  // Only meaningful when operating as platform admin without a JWT session.
  const showPicker = hasAdminToken && !session;
  const products = useQuery({
    queryKey: ["products", "list"],
    queryFn:  () => api.products.list(),
    enabled:  showPicker,
  });
  if (!showPicker) return null;

  const data = (products.data ?? []).map(p => ({ value: p.slug, label: `${p.name} (${p.slug})` }));

  return (
    <Tooltip label="Admin context — every tenant-scoped call is sent with this product slug">
      <Select
        size="xs"
        w={220}
        placeholder={products.isLoading ? "Loading products…" : "Pick a product"}
        value={adminProductSlug}
        data={data}
        searchable
        clearable
        onChange={async (v) => {
          await setAdminProductSlug(v);
          // Bust caches so every page re-fetches under the new product scope.
          qc.removeQueries();
          notify.info("Admin scope updated", v ?? "cleared");
        }}
      />
    </Tooltip>
  );
}

function ActingTenantPicker() {
  const { hasAdminToken, session, adminProductSlug, actingTenantSlug, setActingTenantSlug } = useAuth();
  const qc = useQueryClient();
  // Shown only when there's a product scope to operate inside — both
  // admin-with-product and signed-in users (the latter can act-as their
  // direct children if RBAC allows).
  const showPicker = (hasAdminToken && !!adminProductSlug) || !!session;
  // Tenants for current scope. With actingTenantSlug already set, /tenants
  // returns the child + its kids (not useful for picking a sibling). Clear
  // the acting header first so we see the full picker list.
  const tenants = useQuery({
    queryKey: ["tenants", "picker", adminProductSlug, session?.productSlug],
    queryFn:  () => api.tenants.list(),
    enabled:  showPicker,
  });
  if (!showPicker) return null;

  // The platform's /tenants returns the effective tenant + direct children.
  // For the picker we want all of them flat, marking the root distinctly.
  const data = (tenants.data ?? []).map(t => ({
    value: t.slug,
    label: t.is_root ? `${t.name} (root)` : t.name,
  }));

  return (
    <Tooltip label="Acting tenant — every call carries X-Acting-Tenant-Slug. Clear to operate on the root.">
      <Select
        size="xs"
        w={200}
        placeholder={tenants.isLoading ? "Loading tenants…" : "Act as tenant (root)"}
        value={actingTenantSlug}
        data={data}
        searchable
        clearable
        onChange={async (v) => {
          await setActingTenantSlug(v);
          qc.removeQueries();
          notify.info("Tenant scope updated", v ?? "root");
        }}
      />
    </Tooltip>
  );
}

export function AppShellLayout({ children }: { children: React.ReactNode }) {
  const [opened, { toggle }] = useDisclosure();
  const location = useLocation();
  const navigate = useNavigate();
  const { session, hasAdminToken, signOut, setAdminToken } = useAuth();

  const onLogout = async () => {
    try {
      if (session) await api.auth.logout();
      if (hasAdminToken) {
        await api.auth.clearAdminToken();
        await api.system.setAdminProductSlug(null);
        setAdminToken(false);
      }
      // Always clear acting scope on sign-out — regardless of which mode.
      await api.system.setActingTenantSlug(null);
      signOut();
      notify.info("Signed out");
      navigate("/login");
    } catch (e) {
      notify.error("Sign-out failed", e);
    }
  };

  return (
    <MantineAppShell
      header={{ height: 52 }}
      navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="md"
    >
      <MantineAppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700} size="md">Plynth Admin</Text>
          </Group>
          <Group gap="xs">
            <AdminProductPicker />
            <ActingTenantPicker />
            {session && (
              <Tooltip label={`Signed in as ${session.email} on ${session.productSlug}`}>
                <Badge variant="light" color="brand">
                  {session.email} · {session.productSlug}
                </Badge>
              </Tooltip>
            )}
            {!session && hasAdminToken && (
              <Tooltip label="Authenticated with the platform admin token (super-user across all products)">
                <Badge variant="light" color="grape">platform admin</Badge>
              </Tooltip>
            )}
            {(session || hasAdminToken) && (
              <Button
                size="xs"
                variant="default"
                leftSection={<IconLogout size={14} />}
                onClick={onLogout}
              >
                Sign out
              </Button>
            )}
          </Group>
        </Group>
      </MantineAppShell.Header>

      <MantineAppShell.Navbar p="xs">
        <ScrollArea h="100%">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              component={Link}
              to={item.to}
              active={location.pathname === item.to}
              label={item.label}
              leftSection={item.icon}
              rightSection={
                item.status === "stub"
                  ? <Badge size="xs" color="gray">soon</Badge>
                  : item.status === "admin"
                  ? <Badge size="xs" color="grape">admin</Badge>
                  : undefined
              }
            />
          ))}
        </ScrollArea>
      </MantineAppShell.Navbar>

      <MantineAppShell.Main>{children}</MantineAppShell.Main>
    </MantineAppShell>
  );
}
