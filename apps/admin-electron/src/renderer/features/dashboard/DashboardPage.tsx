import { Anchor, Badge, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { IconCheck, IconShield, IconUser, IconX } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { PageHeader } from "@renderer/components/PageHeader";
import { api } from "@renderer/lib/api";
import { useAuth } from "@renderer/features/auth/useAuth";

export function DashboardPage() {
  const { session, hasAdminToken } = useAuth();

  const baseUrl = useQuery<string>({
    queryKey: ["system", "baseUrl"],
    queryFn:  () => api.system.baseUrl(),
  });

  const products = useQuery({
    queryKey: ["products", "list"],
    queryFn:  () => api.products.list(),
    enabled:  hasAdminToken,
  });

  return (
    <Stack>
      <PageHeader
        title="Dashboard"
        description="At-a-glance health of your platform deployment and current session."
      />

      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Card>
          <Group justify="space-between">
            <Text fw={600}>API endpoint</Text>
            <Badge variant="light" color="brand">connected</Badge>
          </Group>
          <Text size="sm" c="dimmed" mt={4}>{baseUrl.data ?? "—"}</Text>
          <Text size="xs" c="dimmed" mt="xs">
            Change in <Anchor component={Link} to="/settings">Settings</Anchor>.
          </Text>
        </Card>

        <Card>
          <Group justify="space-between">
            <Text fw={600}>User session</Text>
            {session ? (
              <Badge variant="light" color="green" leftSection={<IconCheck size={12} />}>signed in</Badge>
            ) : (
              <Badge variant="light" color="gray" leftSection={<IconX size={12} />}>none</Badge>
            )}
          </Group>
          {session ? (
            <Stack gap={2} mt={4}>
              <Group gap={6}><IconUser size={14} /><Text size="sm">{session.email}</Text></Group>
              <Text size="xs" c="dimmed">Product: {session.productSlug}</Text>
              <Text size="xs" c="dimmed">Token expires {new Date(session.expiresAt).toLocaleString()}</Text>
            </Stack>
          ) : (
            <Text size="xs" c="dimmed" mt="xs">No user session — only admin-token features available.</Text>
          )}
        </Card>

        <Card>
          <Group justify="space-between">
            <Text fw={600}>Platform admin</Text>
            {hasAdminToken ? (
              <Badge variant="light" color="grape" leftSection={<IconShield size={12} />}>unlocked</Badge>
            ) : (
              <Badge variant="light" color="gray">locked</Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed" mt="xs">
            {hasAdminToken
              ? `Cross-product CRUD enabled. ${products.data?.length ?? "…"} product(s).`
              : "Sign in with the platform admin token to enable cross-product CRUD."}
          </Text>
        </Card>
      </SimpleGrid>

      <Card>
        <Title order={5}>What this app manages</Title>
        <Text size="sm" c="dimmed" mt={4}>
          A thin admin surface over the same REST API that powers your products.
          Every action goes through <Text component="span" ff="monospace" size="sm">/api/v1</Text>{" "}
          — the same paths documented in <Text component="span" ff="monospace" size="sm">docs/INTEGRATION.md</Text>.
        </Text>
      </Card>
    </Stack>
  );
}
