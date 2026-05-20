import { useState } from "react";
import {
  Anchor,
  Button,
  Card,
  Center,
  PasswordInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconKey, IconUserCircle } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";

import { api } from "@renderer/lib/api";
import { notify } from "@renderer/lib/notify";
import { useAuthStore } from "@renderer/features/auth/useAuth";

type Mode = "user" | "admin";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("user");
  const [submitting, setSubmitting] = useState(false);

  const userForm = useForm({
    initialValues: { email: "", password: "", productSlug: "platform", tenantSlug: "" },
    validate: {
      email:       (v) => (/.+@.+\..+/.test(v) ? null : "Valid email required"),
      password:    (v) => (v.length >= 8 ? null : "Min 8 characters"),
      productSlug: (v) => (/^[a-z0-9-]+$/.test(v) ? null : "Lowercase letters, digits, hyphens"),
    },
  });

  const adminForm = useForm({
    initialValues: { token: "" },
    validate: {
      token: (v) => (v.length >= 32 ? null : "Token looks too short — typically 64 hex chars"),
    },
  });

  const submitUser = userForm.onSubmit(async (values) => {
    setSubmitting(true);
    try {
      const session = await api.auth.loginAsUser({
        email:       values.email.trim(),
        password:    values.password,
        productSlug: values.productSlug.trim(),
        tenantSlug:  values.tenantSlug.trim() || undefined,
      });
      useAuthStore.getState().signIn(session);
      notify.success("Signed in", `${session.email} on ${session.productSlug}`);
      navigate("/");
    } catch (e) {
      notify.error("Sign-in failed", e);
    } finally {
      setSubmitting(false);
    }
  });

  const submitAdmin = adminForm.onSubmit(async (values) => {
    setSubmitting(true);
    try {
      await api.auth.setAdminToken(values.token.trim());
      // Verify by hitting /admin/products — this validates the token.
      await api.products.list();
      useAuthStore.getState().setAdminToken(true);
      notify.success("Platform admin token saved & verified");
      navigate("/products");
    } catch (e) {
      // Roll back the saved token on verification failure.
      try { await api.auth.clearAdminToken(); } catch { /* ignore */ }
      useAuthStore.getState().setAdminToken(false);
      notify.error("Admin token rejected", e);
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Center mih="100vh" p="md" bg="dark.8">
      <Card w={420} p="xl">
        <Stack gap="md">
          <Stack gap={4} align="center">
            <Title order={3}>Plynth Admin</Title>
            <Text c="dimmed" size="sm">Sign in to manage the platform</Text>
          </Stack>

          <SegmentedControl
            value={mode}
            onChange={(v) => setMode(v as Mode)}
            data={[
              { value: "user",  label: <Stack gap={2} align="center"><IconUserCircle size={16} /> <Text size="xs">User</Text></Stack> },
              { value: "admin", label: <Stack gap={2} align="center"><IconKey size={16} />        <Text size="xs">Platform Admin</Text></Stack> },
            ]}
            fullWidth
          />

          {mode === "user" ? (
            <form onSubmit={submitUser}>
              <Stack>
                <TextInput
                  label="Email"
                  placeholder="admin@example.com"
                  autoComplete="email"
                  withAsterisk
                  {...userForm.getInputProps("email")}
                />
                <PasswordInput
                  label="Password"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  withAsterisk
                  {...userForm.getInputProps("password")}
                />
                <TextInput
                  label="Product slug"
                  description="The product you're signing into"
                  withAsterisk
                  {...userForm.getInputProps("productSlug")}
                />
                <TextInput
                  label="Tenant slug (optional)"
                  description="Only needed if you have the same email in multiple tenants of this product"
                  {...userForm.getInputProps("tenantSlug")}
                />
                <Button type="submit" loading={submitting} fullWidth mt="xs">
                  Sign in
                </Button>
              </Stack>
            </form>
          ) : (
            <form onSubmit={submitAdmin}>
              <Stack>
                <PasswordInput
                  label="Platform admin token"
                  description="Stored in your OS keychain; verified by listing products."
                  placeholder="64-hex from your password manager"
                  withAsterisk
                  {...adminForm.getInputProps("token")}
                />
                <Button type="submit" loading={submitting} fullWidth mt="xs">
                  Save & verify
                </Button>
                <Text size="xs" c="dimmed" ta="center">
                  This unlocks the <Anchor component="span" inherit>Products</Anchor> section
                  (cross-product CRUD). All other sections still require a user sign-in.
                </Text>
              </Stack>
            </form>
          )}
        </Stack>
      </Card>
    </Center>
  );
}
