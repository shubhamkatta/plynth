import { Button, Modal, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";

import { useCreateChildTenant } from "@renderer/features/tenants/useTenants";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function TenantFormModal({ opened, onClose }: Props) {
  const create = useCreateChildTenant();
  const form = useForm({
    initialValues: { name: "", slug: "" },
    validate: {
      name: (v) => (v.trim().length >= 1 ? null : "Name required"),
      slug: (v) => (/^[a-z0-9-]{2,64}$/.test(v) ? null : "2–64 chars: lowercase letters, digits, hyphens"),
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const t = await create.mutateAsync({ name: values.name.trim(), slug: values.slug.trim() });
      notify.success("Child tenant created", `${t.name} (${t.slug})`);
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Create failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="New child tenant" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Name"
            placeholder="Acme West Division"
            withAsterisk
            {...form.getInputProps("name")}
          />
          <TextInput
            label="Slug"
            description="Used in URLs; cannot change. Scoped under your current tenant."
            placeholder="acme-west"
            withAsterisk
            {...form.getInputProps("slug")}
          />
          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
