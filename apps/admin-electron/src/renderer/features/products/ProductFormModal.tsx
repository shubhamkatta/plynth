import { Button, Modal, Stack, Textarea, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";

import { useCreateProduct } from "@renderer/features/products/useProducts";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function ProductFormModal({ opened, onClose }: Props) {
  const create = useCreateProduct();
  const form = useForm({
    initialValues: { name: "", slug: "", description: "" },
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
      });
      notify.success("Product created", `${product.name} (${product.slug})`);
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
          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
