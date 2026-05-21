import {
  Alert,
  Button,
  Divider,
  Modal,
  PasswordInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconInfoCircle } from "@tabler/icons-react";

import { useCreateChildTenant } from "@renderer/features/tenants/useTenants";
import { usePlans } from "@renderer/features/plans/usePlans";
import { useAuth } from "@renderer/features/auth/useAuth";
import { notify } from "@renderer/lib/notify";
import type { TenantType } from "@shared/types";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function TenantFormModal({ opened, onClose }: Props) {
  const create   = useCreateChildTenant();
  const plansQ   = usePlans();
  const { hasAdminToken } = useAuth();

  // Admin-only fields: owner email/password + plan picker. Regular users
  // create tenants without these (their team adds members separately).
  const showAdminBootstrap = hasAdminToken;

  const form = useForm({
    initialValues: {
      name:           "",
      slug:           "",
      type:           "company" as TenantType,
      with_owner:     true,
      owner_email:    "",
      owner_password: "",
      owner_name:     "",
      plan_code:      "",
    },
    validate: {
      name:           (v) => (v.trim().length >= 1 ? null : "Name required"),
      slug:           (v) => (/^[a-z0-9-]{2,64}$/.test(v) ? null : "2–64 chars: lowercase letters, digits, hyphens"),
      owner_email:    (v, vals) => !showAdminBootstrap || !vals.with_owner
        ? null
        : (/.+@.+\..+/.test(v) ? null : "Valid email required"),
      owner_password: (v, vals) => !showAdminBootstrap || !vals.with_owner
        ? null
        : (v.length >= 12 ? null : "Min 12 characters"),
    },
  });

  const planOptions = (plansQ.data ?? [])
    .filter(p => p.is_public && p.is_active)
    .map(p => ({
      value: p.code,
      label: `${p.name} — $${(p.price_cents / 100).toFixed(2)}/${p.interval}`,
    }));

  const submit = form.onSubmit(async (values) => {
    try {
      const includeOwner = showAdminBootstrap && values.with_owner;
      const t = await create.mutateAsync({
        name: values.name.trim(),
        slug: values.slug.trim(),
        type: values.type,
        ...(includeOwner ? {
          owner: {
            email:     values.owner_email.trim(),
            password:  values.owner_password,
            full_name: values.owner_name.trim() || null,
          },
          plan_code: values.plan_code || undefined,
        } : {}),
      });
      notify.success(
        "Tenant created",
        includeOwner
          ? `${t.name} (${t.slug}) + owner ${values.owner_email}`
          : `${t.name} (${t.slug})`,
      );
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Create failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="New tenant" centered size="md">
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Name"
            placeholder="Acme Inc"
            withAsterisk
            {...form.getInputProps("name")}
          />
          <TextInput
            label="Slug"
            description="Used in URLs; cannot change."
            placeholder="acme"
            withAsterisk
            {...form.getInputProps("slug")}
          />

          <Stack gap={4}>
            <Text size="sm" fw={500}>Type</Text>
            <SegmentedControl
              fullWidth
              data={[
                { value: "company",    label: "Company (B2B)" },
                { value: "individual", label: "Individual (B2C)" },
              ]}
              {...form.getInputProps("type")}
            />
          </Stack>

          {showAdminBootstrap && (
            <>
              <Divider label="Bootstrap (admin only)" labelPosition="center" my="xs" />

              <Switch
                label="Create owner user + start trial"
                description="One transaction: tenant + owner with the 'owner' role + a trial subscription on the chosen plan."
                {...form.getInputProps("with_owner", { type: "checkbox" })}
              />

              {form.values.with_owner && (
                <>
                  <TextInput
                    label="Owner email"
                    placeholder="alice@acme.example.com"
                    withAsterisk
                    {...form.getInputProps("owner_email")}
                  />
                  <PasswordInput
                    label="Owner password"
                    description="Share with the owner securely — they can change it after first login."
                    withAsterisk
                    {...form.getInputProps("owner_password")}
                  />
                  <TextInput
                    label="Owner full name"
                    placeholder="Alice Rivers"
                    {...form.getInputProps("owner_name")}
                  />
                  <Select
                    label="Plan (for trial)"
                    description={planOptions.length === 0
                      ? "No plans found — add some on the Plans page first, or accept the cheapest auto-pick."
                      : "Leave blank to auto-pick the cheapest public plan."}
                    placeholder="Cheapest public plan (auto)"
                    data={planOptions}
                    clearable
                    {...form.getInputProps("plan_code")}
                  />
                </>
              )}

              {form.values.with_owner && planOptions.length === 0 && (
                <Alert color="yellow" variant="light" icon={<IconInfoCircle />}>
                  This product has no plans. Trial start will fail — either add a plan first
                  (Plans page) or untoggle bootstrap and add the user separately.
                </Alert>
              )}
            </>
          )}

          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create tenant
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
