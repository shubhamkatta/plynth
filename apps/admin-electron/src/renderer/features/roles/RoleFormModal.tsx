import {
  Button,
  Loader,
  Modal,
  MultiSelect,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";

import {
  useCreateRole,
  usePermissions,
  useRoles,
} from "@renderer/features/roles/useRoles";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened:  boolean;
  onClose: () => void;
}

export function RoleFormModal({ opened, onClose }: Props) {
  const create      = useCreateRole();
  const permissions = usePermissions();
  const rolesQ     = useRoles();
  const takenNames = new Set(
    (rolesQ.data ?? []).map(r => r.name.toLowerCase()),
  );

  const form = useForm({
    initialValues: {
      name:             "",
      description:      "",
      permission_codes: [] as string[],
    },
    validate: {
      name: (v) => {
        const trimmed = v.trim();
        if (trimmed.length === 0)              return "Name is required";
        if (takenNames.has(trimmed.toLowerCase())) return `'${trimmed}' already exists in this product`;
        return null;
      },
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const r = await create.mutateAsync({
        name:             values.name.trim(),
        description:      values.description.trim() || null,
        permission_codes: values.permission_codes,
      });
      notify.success("Role created", r.name);
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Create failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="New role" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Name"
            placeholder="content_editor"
            withAsterisk
            {...form.getInputProps("name")}
          />
          <Textarea
            label="Description"
            placeholder="What can holders of this role do?"
            autosize
            minRows={2}
            {...form.getInputProps("description")}
          />
          {permissions.isLoading ? (
            <Loader size="sm" />
          ) : (
            <MultiSelect
              label="Permissions"
              description="Pick resource:action codes from the global catalog. Wildcards (*:*, users:*) are allowed."
              placeholder="Select permissions"
              data={permissions.data ?? []}
              searchable
              clearable
              {...form.getInputProps("permission_codes")}
            />
          )}
          <Button type="submit" loading={create.isPending} fullWidth mt="sm">
            Create role
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
