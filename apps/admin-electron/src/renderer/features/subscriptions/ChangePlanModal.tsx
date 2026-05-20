import { useMemo, useState } from "react";
import { Button, Modal, Select, Stack, Switch, Text } from "@mantine/core";

import { usePlans, useChangeSubscription } from "@renderer/features/subscriptions/useSubscription";
import { notify } from "@renderer/lib/notify";
import type { Plan } from "@shared/types";

interface Props {
  opened:        boolean;
  onClose:       () => void;
  currentCode?:  string | null;
}

function planLabel(p: Plan): string {
  const price = `$${(p.price_cents / 100).toFixed(2)}`;
  return `${p.name} — ${price}/${p.interval}`;
}

export function ChangePlanModal({ opened, onClose, currentCode }: Props) {
  const plans  = usePlans();
  const change = useChangeSubscription();

  const [planCode,  setPlanCode]  = useState<string | null>(null);
  const [proration, setProration] = useState(true);

  const options = useMemo(
    () =>
      (plans.data ?? [])
        .filter((p) => p.is_active)
        .map((p) => ({ value: p.code, label: planLabel(p) })),
    [plans.data],
  );

  const submit = async () => {
    if (!planCode) {
      notify.warn("Pick a plan", "Choose the plan you want to switch to.");
      return;
    }
    try {
      await change.mutateAsync({ plan_code: planCode, proration });
      notify.success("Plan changed", planCode);
      setPlanCode(null);
      setProration(true);
      onClose();
    } catch (e) {
      notify.error("Change failed", e);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Change plan" centered>
      <Stack>
        <Select
          label="Plan"
          placeholder={plans.isLoading ? "Loading plans..." : "Select a plan"}
          data={options}
          value={planCode}
          onChange={setPlanCode}
          searchable
          withAsterisk
          disabled={plans.isLoading}
          description={
            currentCode
              ? `Current plan: ${currentCode}`
              : "No current plan on file."
          }
        />
        <Switch
          label="Apply proration"
          checked={proration}
          onChange={(e) => setProration(e.currentTarget.checked)}
        />
        <Text size="xs" c="dimmed">
          Bill the difference now (charge or credit) instead of at next renewal.
        </Text>
        <Button onClick={submit} loading={change.isPending} fullWidth mt="sm">
          Confirm change
        </Button>
      </Stack>
    </Modal>
  );
}
