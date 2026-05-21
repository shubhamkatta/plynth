import {
  Alert,
  Button,
  Modal,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconInfoCircle } from "@tabler/icons-react";

import { useCreateProduct } from "@renderer/features/products/useProducts";
import { notify } from "@renderer/lib/notify";
import type { TenantType } from "@shared/types";

interface Props {
  opened: boolean;
  onClose: () => void;
}

const TEMPLATE_PREVIEW: Record<TenantType, string> = {
  company:    "Free · Pro ($49) · Enterprise ($299)",
  individual: "Free · Pro ($9.99) · Max ($19.99)",
};

export function ProductFormModal({ opened, onClose }: Props) {
  const create = useCreateProduct();
  const form = useForm({
    initialValues: {
      name:        "",
      slug:        "",
      description: "",
      tenant_type: "company" as TenantType,
      seed_plans:  true,
    },
    validate: {
      name: (v) => (v.trim().length >= 2 ? null : "Min 2 characters"),
      slug: (v) => (/^[a-z0-9-]+$/.test(v) ? null : "Lowercase letters, digits, hyphens"),
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const product = await create.mutateAsync({
        name:        values.name.trim(),
        slug:        values.slug.trim(),
        description: values.description.trim() || null,
        tenant_type: values.tenant_type,
        seed_plans:  values.seed_plans,
      });
      notify.success(
        "Product created",
        values.seed_plans
          ? `${product.name} (${product.slug}) — plans seeded.`
          : `${product.name} (${product.slug})`,
      );
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Create failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="New product" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Name"
            placeholder="Acme Notes"
            withAsterisk
            {...form.getInputProps("name")}
          />
          <TextInput
            label="Slug"
            description="Used in URLs and the X-Product-Slug header; cannot change."
            placeholder="acme-notes"
            withAsterisk
            {...form.getInputProps("slug")}
          />
          <Textarea
            label="Description"
            placeholder="One-liner describing this product"
            autosize
            minRows={2}
            {...form.getInputProps("description")}
          />

          <Stack gap={4}>
            <Text size="sm" fw={500}>Customer type</Text>
            <SegmentedControl
              fullWidth
              data={[
                { value: "company",    label: "B2B (companies)" },
                { value: "individual", label: "B2C (individuals)" },
              ]}
              {...form.getInputProps("tenant_type")}
            />
            <Text size="xs" c="dimmed">
              Default tenant type for new signups. Both flows work either way —
              this only switches the seeded plan template.
            </Text>
          </Stack>

          <Switch
            label="Seed standard plans"
            description={
              form.values.seed_plans
                ? `Will create: ${TEMPLATE_PREVIEW[form.values.tenant_type]}`
                : "No plans will be created. You'll need to add them on the Plans page before any tenant can sign up."
            }
            {...form.getInputProps("seed_plans", { type: "checkbox" })}
          />

          {!form.values.seed_plans && (
            <Alert color="yellow" variant="light" icon={<IconInfoCircle />}>
              Without plans, tenant signup will fail. You can add plans later from the Plans page.
            </Alert>
          )}

          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create product
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
