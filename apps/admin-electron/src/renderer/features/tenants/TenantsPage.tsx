import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  CopyButton,
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
  IconCalendarTime,
  IconCheck,
  IconCopy,
  IconDotsVertical,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlus,
  IconRefresh,
} from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { TenantExpiryModal } from "@renderer/features/tenants/TenantExpiryModal";
import { TenantFormModal } from "@renderer/features/tenants/TenantFormModal";
import { useSetTenantActive, useTenants } from "@renderer/features/tenants/useTenants";
import { describeError } from "@renderer/lib/api";
import { notify } from "@renderer/lib/notify";
import { useAuth, useEffectiveAuth } from "@renderer/features/auth/useAuth";
import type { Tenant } from "@shared/types";

const statusColor = (s: Tenant["status"]) =>
  s === "active"      ? "green"
  : s === "suspended" ? "yellow"
  : s === "deleted"   ? "red"
  : "gray";

function expiryBadge(t: Tenant): React.ReactNode {
  if (!t.expires_at) return <Text size="xs" c="dimmed">no cap</Text>;
  const at = new Date(t.expires_at);
  const past = at < new Date();
  return (
    <Tooltip label={at.toLocaleString()}>
      <Badge variant={past ? "filled" : "light"} color={past ? "red" : "yellow"}>
        {past ? "expired" : "expires"} {at.toLocaleDateString()}
      </Badge>
    </Tooltip>
  );
}

export function TenantsPage() {
  const [open, setOpen] = useState(false);
  const [expiryTarget, setExpiryTarget] = useState<Tenant | null>(null);
  const { session } = useAuth();
  const { isAuthed, reason } = useEffectiveAuth();
  const q = useTenants();
  const setActive = useSetTenantActive();

  const onToggle = (t: Tenant) => {
    const willActivate = t.status !== "active";
    modals.openConfirmModal({
      title: willActivate ? "Activate tenant?" : "Deactivate tenant?",
      children: (
        <Text size="sm">
          {willActivate
            ? <>Re-enable <strong>{t.name}</strong> ({t.slug}). Users will be able to sign in again.</>
            : <>Deactivate <strong>{t.name}</strong> ({t.slug}). Users will not be able to sign in. This is reversible.</>}
        </Text>
      ),
      labels: { confirm: willActivate ? "Activate" : "Deactivate", cancel: "Cancel" },
      confirmProps: { color: willActivate ? "green" : "yellow" },
      onConfirm: async () => {
        try {
          await setActive.mutateAsync({ id: t.id, active: willActivate });
          notify.success(`Tenant ${willActivate ? "activated" : "deactivated"}`, t.name);
        } catch (e) {
          notify.error("Status change failed", e);
        }
      },
    });
  };

  return (
    <Stack>
      <PageHeader
        title="Tenants"
        description={
          session
            ? `Tenants in product "${session.productSlug}" — your home tenant and its direct children.`
            : "Tenants in the selected product — the platform admin sees the root tenant and its children."
        }
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
              New child tenant
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
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load tenants">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="sm" horizontalSpacing="md" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Slug</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th>Expiry</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text c="dimmed" ta="center" py="lg">
                    No tenants visible in scope.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((t) => (
              <Table.Tr key={t.id}>
                <Table.Td>
                  <Group gap={6}>
                    <Code>{t.slug}</Code>
                    <CopyButton value={t.slug}>
                      {({ copied, copy }) => (
                        <Tooltip label={copied ? "Copied" : "Copy slug"}>
                          <ActionIcon size="xs" variant="subtle" onClick={copy}>
                            {copied ? <IconCheck size={12} /> : <IconCopy size={12} />}
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </CopyButton>
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Text fw={500}>{t.name}</Text>
                  {t.parent_id && (
                    <Text size="xs" c="dimmed">child of {t.parent_id.slice(0, 8)}…</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={t.type === "company" ? "blue" : "teal"}>
                    {t.type}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={statusColor(t.status)}>{t.status}</Badge>
                </Table.Td>
                <Table.Td>
                  {t.is_root
                    ? <Badge variant="outline" color="brand">root</Badge>
                    : <Text size="xs" c="dimmed">child</Text>}
                </Table.Td>
                <Table.Td>{expiryBadge(t)}</Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(t.created_at).toLocaleString()}</Text>
                </Table.Td>
                <Table.Td>
                  <Menu shadow="md" position="bottom-end" withArrow>
                    <Menu.Target>
                      <ActionIcon variant="subtle">
                        <IconDotsVertical size={16} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item
                        leftSection={<IconCalendarTime size={14} />}
                        onClick={() => setExpiryTarget(t)}
                      >
                        Edit expiry
                      </Menu.Item>
                      <Menu.Divider />
                      {t.status === "active" ? (
                        <Menu.Item
                          color="yellow"
                          leftSection={<IconPlayerPause size={14} />}
                          onClick={() => onToggle(t)}
                          disabled={t.is_root}
                        >
                          Deactivate
                        </Menu.Item>
                      ) : (
                        <Menu.Item
                          color="green"
                          leftSection={<IconPlayerPlay size={14} />}
                          onClick={() => onToggle(t)}
                        >
                          Activate
                        </Menu.Item>
                      )}
                    </Menu.Dropdown>
                  </Menu>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <TenantFormModal opened={open} onClose={() => setOpen(false)} />
      <TenantExpiryModal tenant={expiryTarget} onClose={() => setExpiryTarget(null)} />
    </Stack>
  );
}
