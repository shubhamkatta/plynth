import { Button, Modal, NumberInput, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";

import { useGrantCredits } from "@renderer/features/credits/useCredits";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened:  boolean;
  onClose: () => void;
}

interface FormValues {
  feature_key: string;
  amount:      number | "";
  reason:      string;
  reference:   string;
}

export function CreditGrantModal({ opened, onClose }: Props) {
  const grant = useGrantCredits();
  const form  = useForm<FormValues>({
    initialValues: {
      feature_key: "",
      amount:      "" as number | "",
      reason:      "",
      reference:   "",
    },
    validate: {
      feature_key: (v) => {
        const trimmed = v.trim();
        if (!trimmed) return "Feature key required";
        if (trimmed.length > 64) return "Max 64 chars";
        return null;
      },
      amount: (v) => {
        if (typeof v !== "number" || Number.isNaN(v)) return "Amount required";
        if (v < 0.0001) return "Amount must be at least 0.0001";
        return null;
      },
    },
  });

  const submit = form.onSubmit(async (values) => {
    if (typeof values.amount !== "number") return;
    try {
      const w = await grant.mutateAsync({
        feature_key: values.feature_key.trim(),
        amount:      values.amount.toString(),
        reason:      values.reason.trim() || null,
        reference:   values.reference.trim() || null,
      });
      notify.success("Credits granted", `${w.feature_key} → ${w.balance}`);
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Grant failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Grant credits" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Feature key"
            placeholder="ai_tokens"
            maxLength={64}
            withAsterisk
            {...form.getInputProps("feature_key")}
          />
          <NumberInput
            label="Amount"
            placeholder="100"
            min={0.0001}
            decimalScale={4}
            withAsterisk
            {...form.getInputProps("amount")}
          />
          <TextInput
            label="Reason"
            placeholder="Promotional grant"
            {...form.getInputProps("reason")}
          />
          <TextInput
            label="Reference"
            description="Set this to dedupe retries — the platform treats same reference as idempotent."
            placeholder="promo-2026-05-abc123"
            {...form.getInputProps("reference")}
          />
          <Button type="submit" loading={grant.isPending} fullWidth mt="sm">
            Grant
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
