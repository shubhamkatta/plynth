import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Menu,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import {
  IconAlertCircle,
  IconDotsVertical,
  IconPlayerPause,
  IconPlayerPlay,
  IconRefresh,
  IconTrash,
  IconUserPlus,
} from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { UserInviteModal } from "@renderer/features/users/UserInviteModal";
import {
  useRemoveUser,
  useSetUserActive,
  useUsers,
} from "@renderer/features/users/useUsers";
import { describeError } from "@renderer/lib/api";
import { notify } from "@renderer/lib/notify";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";
import type { PlatformUser } from "@shared/types";

export function UsersPage() {
  const [open, setOpen] = useState(false);
  const { isAuthed, reason } = useEffectiveAuth();
  const q = useUsers();
  const setActive = useSetUserActive();
  const remove    = useRemoveUser();

  const onToggle = (u: PlatformUser) => {
    const willActivate = !u.is_active;
    modals.openConfirmModal({
      title: willActivate ? "Activate user?" : "Deactivate user?",
      children: (
        <Text size="sm">
          {willActivate
            ? <>Allow <strong>{u.email}</strong> to sign in again.</>
            : <>Block <strong>{u.email}</strong> from signing in. Existing sessions remain valid until they expire.</>}
        </Text>
      ),
      labels:       { confirm: willActivate ? "Activate" : "Deactivate", cancel: "Cancel" },
      confirmProps: { color: willActivate ? "green" : "yellow" },
      onConfirm: async () => {
        try {
          await setActive.mutateAsync({ id: u.id, active: willActivate });
          notify.success(`User ${willActivate ? "activated" : "deactivated"}`, u.email);
        } catch (e) {
          notify.error("Status change failed", e);
        }
      },
    });
  };

  const onDelete = (u: PlatformUser) => {
    modals.openConfirmModal({
      title: "Delete user?",
      children: (
        <Text size="sm">
          Soft-delete <strong>{u.email}</strong>. Their data is retained but they can no longer sign in.
          This is reversible only by a platform operator.
        </Text>
      ),
      labels:       { confirm: "Delete", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: async () => {
        try {
          await remove.mutateAsync(u.id);
          notify.success("User deleted", u.email);
        } catch (e) {
          notify.error("Delete failed", e);
        }
      },
    });
  };

  return (
    <Stack>
      <PageHeader
        title="Users"
        description="Users in the current tenant scope. The platform admin sees users in the selected product's root tenant; act-as a child tenant to see theirs."
        actions={
          <Group gap="xs">
            <Tooltip label="Refresh">
              <ActionIcon variant="default" onClick={() => q.refetch()} loading={q.isFetching}>
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
            <Button
              leftSection={<IconUserPlus size={16} />}
              onClick={() => setOpen(true)}
              disabled={!isAuthed}
            >
              Invite user
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
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load users">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="sm" horizontalSpacing="md" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Email</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th>Active</Table.Th>
              <Table.Th>Verified</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed" ta="center" py="lg">
                    No users in this tenant yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((u) => (
              <Table.Tr key={u.id}>
                <Table.Td>
                  <Text fw={500}>{u.email}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{u.full_name ?? <Text component="span" c="dimmed">—</Text>}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={u.is_active ? "green" : "gray"}>
                    {u.is_active ? "active" : "disabled"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={u.is_verified ? "blue" : "yellow"}>
                    {u.is_verified ? "verified" : "pending"}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(u.created_at).toLocaleString()}</Text>
                </Table.Td>
                <Table.Td>
                  <Menu shadow="md" position="bottom-end" withArrow>
                    <Menu.Target>
                      <ActionIcon variant="subtle">
                        <IconDotsVertical size={16} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      {u.is_active ? (
                        <Menu.Item
                          color="yellow"
                          leftSection={<IconPlayerPause size={14} />}
                          onClick={() => onToggle(u)}
                        >
                          Deactivate
                        </Menu.Item>
                      ) : (
                        <Menu.Item
                          color="green"
                          leftSection={<IconPlayerPlay size={14} />}
                          onClick={() => onToggle(u)}
                        >
                          Activate
                        </Menu.Item>
                      )}
                      <Menu.Divider />
                      <Menu.Item
                        color="red"
                        leftSection={<IconTrash size={14} />}
                        onClick={() => onDelete(u)}
                      >
                        Delete
                      </Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <UserInviteModal opened={open} onClose={() => setOpen(false)} />
    </Stack>
  );
}
