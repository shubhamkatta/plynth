import { Button, Modal, Stack, TagsInput, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";

import { useInviteUser } from "@renderer/features/users/useUsers";
import { notify } from "@renderer/lib/notify";

interface Props {
  opened: boolean;
  onClose: () => void;
}

export function UserInviteModal({ opened, onClose }: Props) {
  const invite = useInviteUser();
  const form = useForm({
    initialValues: { email: "", full_name: "", role_codes: [] as string[] },
    validate: {
      email: (v) => (/.+@.+\..+/.test(v) ? null : "Valid email required"),
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const u = await invite.mutateAsync({
        email:      values.email.trim(),
        full_name:  values.full_name.trim() || null,
        role_codes: values.role_codes,
      });
      notify.success("User invited", u.email);
      form.reset();
      onClose();
    } catch (e) {
      notify.error("Invite failed", e);
    }
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Invite user" centered>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label="Email"
            placeholder="alice@example.com"
            autoComplete="email"
            withAsterisk
            {...form.getInputProps("email")}
          />
          <TextInput
            label="Full name"
            placeholder="Alice Rivers"
            {...form.getInputProps("full_name")}
          />
          <TagsInput
            label="Role codes"
            description="Per-product role codes from your roles catalogue (e.g. admin, member)."
            placeholder="Add role and press Enter"
            {...form.getInputProps("role_codes")}
          />
          <Button type="submit" loading={invite.isPending} fullWidth mt="sm">
            Invite
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
