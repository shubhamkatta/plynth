import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  NumberInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCoin,
  IconRefresh,
} from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { CreditGrantModal } from "@renderer/features/credits/CreditGrantModal";
import { useLedger, useWallets } from "@renderer/features/credits/useCredits";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";
import { describeError } from "@renderer/lib/api";
import type { CreditEntryType } from "@shared/types";

const ENTRY_COLOR: Record<CreditEntryType, string> = {
  grant:      "green",
  debit:      "red",
  refund:     "blue",
  expiry:     "gray",
  adjustment: "yellow",
};

const POSITIVE_ENTRIES: ReadonlySet<CreditEntryType> = new Set<CreditEntryType>(
  ["grant", "refund", "adjustment"],
);

function signedAmount(entryType: CreditEntryType, amount: string): string {
  return POSITIVE_ENTRIES.has(entryType) ? `+${amount}` : `-${amount}`;
}

function truncateRef(ref: string): string {
  return ref.length > 8 ? `${ref.slice(0, 8)}…` : ref;
}

export function CreditsPage() {
  const [open, setOpen]   = useState(false);
  const [limit, setLimit] = useState<number>(100);
  const { isAuthed, reason } = useEffectiveAuth();
  const wallets           = useWallets();
  const ledger            = useLedger(limit);

  return (
    <Stack>
      <PageHeader
        title="Credits"
        description="Per-tenant credit wallets and append-only ledger entries."
        actions={
          <Group gap="xs">
            <Tooltip label="Refresh">
              <ActionIcon
                variant="default"
                onClick={() => {
                  void wallets.refetch();
                  void ledger.refetch();
                }}
                loading={wallets.isFetching || ledger.isFetching}
              >
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
            <Button
              leftSection={<IconCoin size={16} />}
              onClick={() => setOpen(true)}
              disabled={!isAuthed}
            >
              Grant credits
            </Button>
          </Group>
        }
      />

      {!isAuthed && (
        <Alert color="yellow" icon={<IconAlertCircle />} title="No product scope">
          {reason}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="md">
        <Card p="md" withBorder>
          <Stack gap="sm">
            <Title order={4}>Wallets</Title>

            {wallets.isError && (
              <Alert color="red" icon={<IconAlertCircle />} title="Failed to load wallets">
                {describeError(wallets.error)}
              </Alert>
            )}

            <Table verticalSpacing="xs" horizontalSpacing="md" striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Feature key</Table.Th>
                  <Table.Th>Balance</Table.Th>
                  <Table.Th>Updated</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {wallets.data?.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={3}>
                      <Text c="dimmed" ta="center" py="lg">
                        No wallets yet.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {wallets.data?.map((w) => (
                  <Table.Tr key={w.id}>
                    <Table.Td>
                      <Text fw={500}>{w.feature_key}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Code>{w.balance}</Code>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {new Date(w.updated_at).toLocaleString()}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Card>

        <Card p="md" withBorder>
          <Stack gap="sm">
            <Group justify="space-between" align="flex-end">
              <Title order={4}>Recent ledger</Title>
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
            </Group>

            {ledger.isError && (
              <Alert color="red" icon={<IconAlertCircle />} title="Failed to load ledger">
                {describeError(ledger.error)}
              </Alert>
            )}

            <Table verticalSpacing="xs" horizontalSpacing="md" striped stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>When</Table.Th>
                  <Table.Th>Entry type</Table.Th>
                  <Table.Th>Amount</Table.Th>
                  <Table.Th>Balance after</Table.Th>
                  <Table.Th>Reason</Table.Th>
                  <Table.Th>Reference</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {ledger.data?.length === 0 && (
                  <Table.Tr>
                    <Table.Td colSpan={6}>
                      <Text c="dimmed" ta="center" py="lg">
                        No ledger entries yet.
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                )}
                {ledger.data?.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {new Date(row.created_at).toLocaleString()}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={ENTRY_COLOR[row.entry_type]}>
                        {row.entry_type}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Code>{signedAmount(row.entry_type, row.amount)}</Code>
                    </Table.Td>
                    <Table.Td>
                      <Code>{row.balance_after}</Code>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">
                        {row.reason ?? <Text component="span" c="dimmed">—</Text>}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {row.reference
                        ? <Code style={{ fontSize: 11 }}>{truncateRef(row.reference)}</Code>
                        : <Text size="xs" c="dimmed">—</Text>}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stack>
        </Card>
      </SimpleGrid>

      <CreditGrantModal opened={open} onClose={() => setOpen(false)} />
    </Stack>
  );
}
