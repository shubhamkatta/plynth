import {
  Button,
  Modal,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";

import { useCreatePlan, usePlans } from "@renderer/features/plans/usePlans";
import { notify } from "@renderer/lib/notify";
import type { BillingInterval } from "@shared/types";

interface Props {
  opened: boolean;
  onClose: () => void;
}

interface FormValues {
  code:         string;
  name:         string;
  description:  string;
  price_dollars: number | "";
  currency:     string;
  interval:     BillingInterval;
  trial_days:   number | "";
  is_public:    boolean;
}

const CODE_PATTERN = /^[a-z0-9_-]+$/;

export function PlanFormModal({ opened, onClose }: Props) {
  const create   = useCreatePlan();
  const plansQ   = usePlans();
  const takenCodes = new Set((plansQ.data ?? []).map(p => p.code));

  const form = useForm<FormValues>({
    initialValues: {
      code:          "",
      name:          "",
      description:   "",
      price_dollars: 0,
      currency:      "USD",
      interval:      "month",
      trial_days:    0,
      is_public:     true,
    },
    validate: {
      code: (v) => {
        const trimmed = v.trim();
        if (trimmed.length === 0)            return "Code is required";
        if (!CODE_PATTERN.test(trimmed))     return "Lowercase letters, digits, _ and - only";
        if (takenCodes.has(trimmed))         return `'${trimmed}' already exists — pick another or edit it on the Plans table`;
        return null;
      },
      name: (v) => (v.trim().length === 0 ? "Name is required" : null),
      price_dollars: (v) =>
        v === "" || Number.isNaN(Number(v)) || Number(v) < 0
          ? "Price must be 0 or greater"
          : null,
      trial_days: (v) =>
        v === "" || Number.isNaN(Number(v)) || Number(v) < 0
          ? "Trial days must be 0 or greater"
          : null,
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const priceDollars = Number(values.price_dollars);
      const priceCents   = Math.round(priceDollars * 100);
      const trialDays    = Number(values.trial_days);

      const plan = await create.mutateAsync({
        code:        values.code.trim(),
        name:        values.name.trim(),
        description: values.description.trim() || null,
        price_cents: priceCents,
        currency:    values.currency,
        interval:    values.interval,
        trial_days:  trialDays,
        is_public:   values.is_public,
      });
      notify.success("Plan created", plan.code);
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Create plan failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="New plan" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Code"
            description={
              takenCodes.size > 0
                ? `Taken: ${[...takenCodes].sort().join(", ")}`
                : "Stable identifier (lowercase, digits, _ and - only). Cannot be changed."
            }
            placeholder="pro_monthly"
            withAsterisk
            {...form.getInputProps("code")}
          />
          <TextInput
            label="Name"
            placeholder="Pro"
            withAsterisk
            {...form.getInputProps("name")}
          />
          <Textarea
            label="Description"
            placeholder="What does this plan include?"
            autosize
            minRows={2}
            {...form.getInputProps("description")}
          />
          <NumberInput
            label="Price"
            description="In whole currency units (e.g. 9.99). Sent as cents."
            min={0}
            decimalScale={2}
            fixedDecimalScale
            step={0.01}
            withAsterisk
            {...form.getInputProps("price_dollars")}
          />
          <Select
            label="Currency"
            data={["USD", "EUR", "GBP"]}
            allowDeselect={false}
            {...form.getInputProps("currency")}
          />
          <Stack gap={4}>
            <label style={{ fontSize: 14, fontWeight: 500 }}>Interval</label>
            <SegmentedControl
              data={[
                { label: "Monthly",  value: "month"    },
                { label: "Yearly",   value: "year"     },
                { label: "One-time", value: "one_time" },
              ]}
              {...form.getInputProps("interval")}
            />
          </Stack>
          <NumberInput
            label="Trial days"
            min={0}
            {...form.getInputProps("trial_days")}
          />
          <Switch
            label="Public"
            description="Visible to tenants on the plans catalogue."
            {...form.getInputProps("is_public", { type: "checkbox" })}
          />
          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create plan
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
