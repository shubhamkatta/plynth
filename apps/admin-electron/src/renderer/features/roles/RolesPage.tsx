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
import { RoleFormModal } from "@renderer/features/roles/RoleFormModal";
import { useRoles } from "@renderer/features/roles/useRoles";
import { describeError } from "@renderer/lib/api";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";

export function RolesPage() {
  const [open, setOpen] = useState(false);
  const { isAuthed, reason } = useEffectiveAuth();
  const q               = useRoles();

  return (
    <Stack>
      <PageHeader
        title="Roles"
        description="Per-product role catalogue. System roles are seeded automatically; custom roles assemble permissions from the global catalog."
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
              disabled={!isAuthed}
            >
              New role
            </Button>
          </Group>
        }
      />

      {!isAuthed && (
        <Alert color="yellow" icon={<IconAlertCircle />} title="No product scope">
          {reason}
        </Alert>
      )}

      {q.isError && (
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load roles">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="sm" horizontalSpacing="md" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Description</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Permissions</Table.Th>
              <Table.Th>Created</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" ta="center" py="lg">
                    No roles in this product yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>
                  <Text fw={500}>{r.name}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">
                    {r.description ?? <Text component="span" c="dimmed">—</Text>}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={r.is_system ? "grape" : "gray"}>
                    {r.is_system ? "system" : "custom"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Tooltip
                    multiline
                    w={280}
                    withArrow
                    label={
                      r.permissions.length === 0
                        ? "No permissions"
                        : r.permissions.join(", ")
                    }
                  >
                    <Badge variant="light" color="blue" style={{ cursor: "help" }}>
                      {r.permissions.length}
                    </Badge>
                  </Tooltip>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(r.created_at).toLocaleString()}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <RoleFormModal opened={open} onClose={() => setOpen(false)} />
    </Stack>
  );
}
