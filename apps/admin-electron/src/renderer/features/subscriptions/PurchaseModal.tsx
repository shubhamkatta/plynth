import { useMemo, useState } from "react";
import { Button, Modal, Select, Stack } from "@mantine/core";

import { usePlans, usePurchaseSubscription } from "@renderer/features/subscriptions/useSubscription";
import { notify } from "@renderer/lib/notify";
import type { Plan } from "@shared/types";

interface Props {
  opened:  boolean;
  onClose: () => void;
}

function planLabel(p: Plan): string {
  const price = `$${(p.price_cents / 100).toFixed(2)}`;
  return `${p.name} — ${price}/${p.interval}`;
}

export function PurchaseModal({ opened, onClose }: Props) {
  const plans    = usePlans();
  const purchase = usePurchaseSubscription();

  const [planCode, setPlanCode] = useState<string | null>(null);

  const options = useMemo(
    () =>
      (plans.data ?? [])
        .filter((p) => p.is_active && p.is_public)
        .map((p) => ({ value: p.code, label: planLabel(p) })),
    [plans.data],
  );

  const submit = async () => {
    if (!planCode) {
      notify.warn("Pick a plan", "Choose the plan you want to purchase.");
      return;
    }
    try {
      await purchase.mutateAsync({ plan_code: planCode });
      notify.success("Subscription started", planCode);
      setPlanCode(null);
      onClose();
    } catch (e) {
      notify.error("Purchase failed", e);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Purchase subscription" centered>
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
        />
        <Button onClick={submit} loading={purchase.isPending} fullWidth mt="sm">
          Start subscription
        </Button>
      </Stack>
    </Modal>
  );
}
