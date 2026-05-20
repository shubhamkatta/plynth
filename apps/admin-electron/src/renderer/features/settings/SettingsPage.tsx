import { useEffect, useState } from "react";
import { Alert, Button, Card, Group, Stack, Text, TextInput } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { IconAlertTriangle, IconExternalLink } from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { api } from "@renderer/lib/api";
import { notify } from "@renderer/lib/notify";
import { useAuth } from "@renderer/features/auth/useAuth";

export function SettingsPage() {
  const qc = useQueryClient();
  const { hasAdminToken, signOut, setAdminToken } = useAuth();
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.system.baseUrl().then(setBaseUrl).catch(() => setBaseUrl(""));
  }, []);

  const saveBaseUrl = async () => {
    setBusy(true);
    try {
      const url = baseUrl.trim().replace(/\/+$/, "");
      if (!/^https?:\/\//.test(url)) {
        notify.warn("Invalid URL", "Must start with http:// or https://");
        return;
      }
      await api.system.setBaseUrl(url);
      await qc.invalidateQueries();
      notify.success("API endpoint updated");
    } catch (e) {
      notify.error("Save failed", e);
    } finally {
      setBusy(false);
    }
  };

  const clearAdmin = async () => {
    try {
      await api.auth.clearAdminToken();
      setAdminToken(false);
      notify.info("Platform admin token cleared");
    } catch (e) {
      notify.error("Clear failed", e);
    }
  };

  const fullLogout = async () => {
    try {
      await api.auth.logout();
      await api.auth.clearAdminToken();
      signOut();
      setAdminToken(false);
      notify.info("All credentials cleared");
    } catch (e) {
      notify.error("Logout failed", e);
    }
  };

  return (
    <Stack>
      <PageHeader title="Settings" description="Per-machine app configuration. Nothing here syncs across devices." />

      <Card>
        <Text fw={600} mb="xs">API endpoint</Text>
        <Text size="xs" c="dimmed" mb="sm">
          Base URL for every request. Defaults to <Text component="span" ff="monospace" size="xs">https://api.example.com</Text>.
        </Text>
        <Group gap="xs" align="end">
          <TextInput
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.currentTarget.value)}
            placeholder="https://api.example.com"
            style={{ flex: 1 }}
          />
          <Button onClick={saveBaseUrl} loading={busy}>Save</Button>
          <Button
            variant="default"
            leftSection={<IconExternalLink size={14} />}
            onClick={() => api.system.openExternal(`${baseUrl}/docs`).catch(() => {})}
            disabled={!baseUrl}
          >
            Open /docs
          </Button>
        </Group>
      </Card>

      <Card>
        <Text fw={600} mb="xs">Credentials</Text>
        <Text size="xs" c="dimmed" mb="sm">
          Stored in your OS keychain (macOS Keychain / Windows Credential Manager / libsecret).
        </Text>
        <Group gap="xs">
          <Button
            variant="default"
            color="yellow"
            disabled={!hasAdminToken}
            onClick={clearAdmin}
          >
            Clear platform admin token
          </Button>
          <Button color="red" variant="light" onClick={fullLogout}>
            Sign out & forget everything
          </Button>
        </Group>
      </Card>

      <Alert color="brand" icon={<IconAlertTriangle />} title="About this app">
        Admin client for the Plynth platform. All operations go through the documented REST API —
        see <Text component="span" ff="monospace" size="sm">docs/INTEGRATION.md</Text> in the repo for the
        full surface.
      </Alert>
    </Stack>
  );
}
