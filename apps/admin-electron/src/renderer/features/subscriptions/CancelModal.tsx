import { useState } from "react";
import { Button, Modal, Stack, Switch, Text, Textarea } from "@mantine/core";

import { useCancelSubscription } from "@renderer/features/subscriptions/useSubscription";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened:  boolean;
  onClose: () => void;
}

export function CancelModal({ opened, onClose }: Props) {
  const cancel = useCancelSubscription();

  const [atPeriodEnd, setAtPeriodEnd] = useState(true);
  const [reason,      setReason]      = useState("");

  const submit = async () => {
    try {
      await cancel.mutateAsync({
        at_period_end: atPeriodEnd,
        reason:        reason.trim() ? reason.trim() : null,
      });
      notify.success(
        "Subscription cancelled",
        atPeriodEnd ? "Will end at period end." : "Cancelled immediately.",
      );
      setAtPeriodEnd(true);
      setReason("");
      onClose();
    } catch (e) {
      notify.error("Cancel failed", e);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Cancel subscription" centered>
      <Stack>
        <Switch
          label="Cancel at period end"
          checked={atPeriodEnd}
          onChange={(e) => setAtPeriodEnd(e.currentTarget.checked)}
        />
        <Text size="xs" c="dimmed">
          {atPeriodEnd
            ? "Subscription remains active until the end of the current billing period, then transitions to cancelled. No refund."
            : "Cancel immediately. Access is revoked now; remaining period is forfeited."}
        </Text>
        <Textarea
          label="Reason (optional)"
          placeholder="Why is the customer cancelling?"
          value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
          maxLength={255}
          autosize
          minRows={2}
          maxRows={4}
        />
        <Button
          onClick={submit}
          loading={cancel.isPending}
          color="red"
          fullWidth
          mt="sm"
        >
          Confirm cancel
        </Button>
      </Stack>
    </Modal>
  );
}
