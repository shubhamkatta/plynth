import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Card,
  Code,
  Group,
  NumberInput,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { IconAlertCircle, IconRefresh } from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { api, describeError } from "@renderer/lib/api";
import type { AuditEntry } from "@shared/types";

export function AuditPage() {
  const [limit, setLimit] = useState<number>(100);
  const q = useQuery<AuditEntry[]>({
    queryKey: ["audit", "list", limit],
    queryFn:  () => api.audit.list({ limit }),
  });

  return (
    <Stack>
      <PageHeader
        title="Audit log"
        description="Append-only record of every state-changing action. Currently sourced from the credits ledger as a stand-in until /audit ships (see ARCHITECTURE.md § 6)."
        actions={
          <Group gap="xs">
            <NumberInput
              size="xs"
              value={limit}
              min={10}
              max={500}
              step={50}
              onChange={(v) => setLimit(typeof v === "number" ? v : 100)}
              w={110}
              label="Rows"
              labelProps={{ size: "xs" }}
            />
            <Tooltip label="Refresh">
              <ActionIcon variant="default" onClick={() => q.refetch()} loading={q.isFetching}>
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        }
      />

      {q.isError && (
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load audit log">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="xs" horizontalSpacing="md" striped stickyHeader>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>When</Table.Th>
              <Table.Th>Action</Table.Th>
              <Table.Th>Resource</Table.Th>
              <Table.Th>Actor</Table.Th>
              <Table.Th>Acting from</Table.Th>
              <Table.Th>Request</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed" ta="center" py="lg">No audit entries to show.</Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td>
                  <Text size="xs" c="dimmed">{new Date(e.created_at).toLocaleString()}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color="brand">{e.action}</Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{e.resource_type ?? "—"}</Text>
                  {e.resource_id && (
                    <Code style={{ fontSize: 10 }}>{e.resource_id.slice(0, 8)}…</Code>
                  )}
                </Table.Td>
                <Table.Td>
                  <Code style={{ fontSize: 11 }}>{e.actor_user_id?.slice(0, 8) ?? "system"}</Code>
                </Table.Td>
                <Table.Td>
                  {e.acting_from_tenant_id
                    ? <Code style={{ fontSize: 11 }}>{e.acting_from_tenant_id.slice(0, 8)}…</Code>
                    : <Text size="xs" c="dimmed">—</Text>}
                </Table.Td>
                <Table.Td>
                  {e.request_id
                    ? <Code style={{ fontSize: 11 }}>{e.request_id.slice(0, 8)}…</Code>
                    : <Text size="xs" c="dimmed">—</Text>}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
