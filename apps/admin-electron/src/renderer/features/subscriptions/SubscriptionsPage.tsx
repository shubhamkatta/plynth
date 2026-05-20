import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconRefresh,
  IconShoppingCartPlus,
} from "@tabler/icons-react";

import { PageHeader } from "@renderer/components/PageHeader";
import { useEffectiveAuth } from "@renderer/features/auth/useAuth";
import { useSubscription } from "@renderer/features/subscriptions/useSubscription";
import { ChangePlanModal } from "@renderer/features/subscriptions/ChangePlanModal";
import { CancelModal } from "@renderer/features/subscriptions/CancelModal";
import { PurchaseModal } from "@renderer/features/subscriptions/PurchaseModal";
import { describeError } from "@renderer/lib/api";
import type { Subscription, SubscriptionStatus } from "@shared/types";

function statusColor(s: SubscriptionStatus): string {
  switch (s) {
    case "active":
    case "trial":
      return "green";
    case "past_due":
    case "grace":
      return "yellow";
    case "suspended":
    case "cancelled":
      return "red";
    default:
      return "gray";
  }
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

interface FieldProps {
  label:    string;
  children: React.ReactNode;
}

function Field({ label, children }: FieldProps) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text size="sm">{children}</Text>
    </Stack>
  );
}

interface DetailsProps {
  sub: Subscription;
}

function SubscriptionDetails({ sub }: DetailsProps) {
  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between" wrap="nowrap">
          <Stack gap={2}>
            <Text size="lg" fw={600}>{sub.plan_code}</Text>
            <Text size="xs" c="dimmed">Plan id: {sub.plan_id}</Text>
          </Stack>
          <Group gap="xs">
            <Badge color={statusColor(sub.status)} variant="light" size="lg">
              {sub.status}
            </Badge>
            <Badge
              color={sub.has_access ? "green" : "gray"}
              variant="outline"
              size="lg"
            >
              {sub.has_access ? "has access" : "no access"}
            </Badge>
          </Group>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <Field label="Current period start">{formatDate(sub.current_period_start)}</Field>
          <Field label="Current period end">{formatDate(sub.current_period_end)}</Field>
          <Field label="Trial end">{formatDate(sub.trial_end)}</Field>
          <Field label="Grace end">{formatDate(sub.grace_ends_at)}</Field>
          <Field label="Cancel at period end">
            <Badge
              variant="light"
              color={sub.cancel_at_period_end ? "yellow" : "gray"}
            >
              {sub.cancel_at_period_end ? "yes" : "no"}
            </Badge>
          </Field>
          <Field label="Cancelled at">{formatDate(sub.cancelled_at)}</Field>
        </SimpleGrid>
      </Stack>
    </Card>
  );
}

export function SubscriptionsPage() {
  const { isAuthed, reason } = useEffectiveAuth();
  const q           = useSubscription();

  const [changeOpen,   setChangeOpen]   = useState(false);
  const [cancelOpen,   setCancelOpen]   = useState(false);
  const [purchaseOpen, setPurchaseOpen] = useState(false);

  const sub          = q.data ?? null;
  const isCancelled  = sub?.status === "cancelled";
  const actionsDisabled = !sub || isCancelled;

  return (
    <Stack>
      <PageHeader
        title="Subscription"
        description="The current tenant's subscription, scoped from your auth context. Use Change plan or Cancel to manage it."
        actions={
          <Group gap="xs">
            <Tooltip label="Refresh">
              <ActionIcon
                variant="default"
                onClick={() => q.refetch()}
                loading={q.isFetching}
              >
                <IconRefresh size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        }
      />

      {!isAuthed && (
        <Alert color="yellow" icon={<IconAlertCircle />} title="No product scope">
          {reason}
        </Alert>
      )}

      {isAuthed && q.isError && (
        <Alert color="red" icon={<IconAlertCircle />} title="Failed to load subscription">
          {describeError(q.error)}
        </Alert>
      )}

      {isAuthed && q.isLoading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}

      {isAuthed && !q.isLoading && !q.isError && sub === null && (
        <Card withBorder>
          <Stack align="flex-start">
            <Text fw={600}>No active subscription</Text>
            <Text size="sm" c="dimmed">
              This tenant doesn't have a subscription yet. Purchase one to grant access.
            </Text>
            <Button
              leftSection={<IconShoppingCartPlus size={16} />}
              onClick={() => setPurchaseOpen(true)}
            >
              Purchase
            </Button>
          </Stack>
        </Card>
      )}

      {isAuthed && sub && (
        <>
          <SubscriptionDetails sub={sub} />
          <Group>
            <Button
              variant="default"
              onClick={() => setChangeOpen(true)}
              disabled={actionsDisabled}
            >
              Change plan
            </Button>
            <Button
              color="red"
              variant="light"
              onClick={() => setCancelOpen(true)}
              disabled={actionsDisabled || sub.cancel_at_period_end}
            >
              Cancel
            </Button>
          </Group>
        </>
      )}

      <ChangePlanModal
        opened={changeOpen}
        onClose={() => setChangeOpen(false)}
        currentCode={sub?.plan_code ?? null}
      />
      <CancelModal opened={cancelOpen} onClose={() => setCancelOpen(false)} />
      <PurchaseModal opened={purchaseOpen} onClose={() => setPurchaseOpen(false)} />
    </Stack>
  );
}
