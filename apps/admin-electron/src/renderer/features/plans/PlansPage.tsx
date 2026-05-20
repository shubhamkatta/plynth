import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconPlus,
  IconRefresh,
} from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { PlanFormModal } from "@renderer/features/plans/PlanFormModal";
import { usePlans } from "@renderer/features/plans/usePlans";
import { describeError } from "@renderer/lib/api";
import type { BillingInterval } from "@shared/types";

function formatPrice(cents: number, currency: string): string {
  const amount = cents / 100;
  try {
    return new Intl.NumberFormat(undefined, {
      style:    "currency",
      currency,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

function formatInterval(interval: BillingInterval): string {
  switch (interval) {
    case "month":    return "Monthly";
    case "year":     return "Yearly";
    case "one_time": return "One-time";
  }
}

export function PlansPage() {
  const [open, setOpen] = useState(false);
  const q = usePlans();

  return (
    <Stack>
      <PageHeader
        title="Plans"
        description="Per-product plan catalogue. Owns price + entitlements; subscriptions reference them by code."
        actions={
          <Group gap="xs">
            <Tooltip label="Refresh">
              <ActionIcon variant="default" onClick={() => q.refetch()} loading={q.isFetching}>
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
            <Button
              leftSection={<IconPlus size={16} />}
              onClick={() => setOpen(true)}
            >
              New plan
            </Button>
          </Group>
        }
      />

      {q.isError && (
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load plans">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="sm" horizontalSpacing="md" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Code</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th>Price</Table.Th>
              <Table.Th>Interval</Table.Th>
              <Table.Th>Trial</Table.Th>
              <Table.Th>Public</Table.Th>
              <Table.Th>Active</Table.Th>
              <Table.Th>Created</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text c="dimmed" ta="center" py="lg">
                    No plans yet. Click <strong>New plan</strong> to create one.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>
                  <Text fw={500} ff="monospace">{p.code}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{p.name}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatPrice(p.price_cents, p.currency)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatInterval(p.interval)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c={p.trial_days > 0 ? undefined : "dimmed"}>
                    {p.trial_days > 0 ? `${p.trial_days} days` : "—"}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={p.is_public ? "blue" : "gray"}>
                    {p.is_public ? "public" : "private"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={p.is_active ? "green" : "gray"}>
                    {p.is_active ? "active" : "archived"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(p.created_at).toLocaleString()}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <PlanFormModal opened={open} onClose={() => setOpen(false)} />
    </Stack>
  );
}
