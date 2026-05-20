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
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconAlertCircle, IconCheck, IconCopy, IconPlus, IconRefresh } from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { ProductFormModal } from "@renderer/features/products/ProductFormModal";
import { useProducts } from "@renderer/features/products/useProducts";
import { describeError } from "@renderer/lib/api";
import { useAuth } from "@renderer/features/auth/useAuth";

export function ProductsPage() {
  const [open, setOpen] = useState(false);
  const { hasAdminToken } = useAuth();
  const q = useProducts();

  return (
    <Stack>
      <PageHeader
        title="Products"
        description="Each product is an isolated tenant universe. Cross-product admin only — requires the platform admin token."
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
              disabled={!hasAdminToken}
            >
              New product
            </Button>
          </Group>
        }
      />

      {!hasAdminToken && (
        <Alert color="yellow" icon={<IconAlertCircle />} title="Platform admin token required">
          Listing and creating products is a cross-product operation — sign in via the
          <Text component="span" fw={600}> Platform Admin </Text>
          tab on the login page to enable.
        </Alert>
      )}

      {q.isError && (
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load products">
          {describeError(q.error)}
        </Alert>
      )}

      <Card p={0}>
        <Table verticalSpacing="sm" horizontalSpacing="md" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Slug</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data?.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" ta="center" py="lg">
                    No products yet. Click <strong>New product</strong> to bootstrap one.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {q.data?.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td>
                  <Group gap={6}>
                    <Code>{p.slug}</Code>
                    <CopyButton value={p.slug}>
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
                  <Text fw={500}>{p.name}</Text>
                  {p.description && (
                    <Text size="xs" c="dimmed">{p.description}</Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Badge
                    variant="light"
                    color={p.status === "active" ? "green" : p.status === "disabled" ? "yellow" : "gray"}
                  >
                    {p.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{new Date(p.created_at).toLocaleString()}</Text>
                </Table.Td>
                <Table.Td />
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <ProductFormModal opened={open} onClose={() => setOpen(false)} />
    </Stack>
  );
}
