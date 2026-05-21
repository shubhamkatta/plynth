import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Button,
  CopyButton,
  Modal,
  PasswordInput,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  IconAlertTriangle,
  IconCheck,
  IconCopy,
  IconKey,
  IconRefresh,
} from "@tabler/icons-react";

import { useInviteUser, useUsers } from "@renderer/features/users/useUsers";
import { notify } from "@renderer/lib/notify";
import type { InviteUserResponse } from "@shared/types";

interface Props {
  opened: boolean;
  onClose: () => void;
}

function generateReadablePassword(): string {
  // 16 hex chars — strong (64 bits of entropy) and easy to copy/share.
  // crypto.getRandomValues lives on the renderer's `window.crypto`.
  const buf = new Uint8Array(8);
  window.crypto.getRandomValues(buf);
  return Array.from(buf, b => b.toString(16).padStart(2, "0")).join("");
}

export function UserInviteModal({ opened, onClose }: Props) {
  const invite = useInviteUser();
  const usersQ = useUsers();
  const takenEmails = new Set(
    (usersQ.data ?? []).map(u => u.email.toLowerCase()),
  );

  // Post-success: show the credential card with a Copy button.
  // The credential disappears the moment this modal closes — the platform
  // can't return it again.
  const [credential, setCredential] = useState<InviteUserResponse | null>(null);

  const form = useForm({
    initialValues: {
      email:            "",
      full_name:        "",
      role_codes:       [] as string[],
      initial_password: "",
    },
    validate: {
      email: (v) => {
        const trimmed = v.trim().toLowerCase();
        if (!/.+@.+\..+/.test(trimmed))   return "Valid email required";
        if (takenEmails.has(trimmed))     return "A user with this email already exists in this tenant";
        return null;
      },
      initial_password: (v) =>
        v.length === 0 || v.length >= 12
          ? null
          : "Min 12 characters (leave blank to auto-generate)",
    },
  });

  const submit = form.onSubmit(async (values) => {
    try {
      const result = await invite.mutateAsync({
        email:      values.email.trim(),
        full_name:  values.full_name.trim() || null,
        role_codes: values.role_codes,
        ...(values.initial_password ? { initial_password: values.initial_password } : {}),
      });
      // Surface the one-shot password — don't toast and close; the admin
      // needs to copy it before dismissing.
      setCredential(result);
      form.reset();
      notify.success("User created", `${result.email} added`);
    } catch (e) {
      notify.error("Invite failed", e);
    }
  });

  const closeAll = () => {
    setCredential(null);
    onClose();
  };

  if (credential) {
    return (
      <Modal opened={opened} onClose={closeAll} title="Share these credentials" centered>
        <Stack>
          <Alert color="yellow" icon={<IconAlertTriangle />} title="Show once">
            The platform doesn't store the plaintext password. Copy it now and
            share with the user over a secure channel — once you close this
            dialog, it's gone for good.
          </Alert>
          <TextInput
            label="Email"
            value={credential.email}
            readOnly
            rightSection={
              <CopyButton value={credential.email}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? "Copied" : "Copy"}>
                    <ActionIcon variant="subtle" onClick={copy}>
                      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                    </ActionIcon>
                  </Tooltip>
                )}
              </CopyButton>
            }
          />
          <PasswordInput
            label="Password (one-shot)"
            value={credential.initial_password}
            visible
            readOnly
            rightSection={
              <CopyButton value={credential.initial_password}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? "Copied" : "Copy"}>
                    <ActionIcon variant="subtle" onClick={copy}>
                      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                    </ActionIcon>
                  </Tooltip>
                )}
              </CopyButton>
            }
          />
          <Text size="xs" c="dimmed">
            The user can change this password from their profile after first login.
          </Text>
          <Button onClick={closeAll} mt="sm">I've shared them — close</Button>
        </Stack>
      </Modal>
    );
  }

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
          <PasswordInput
            label="Initial password"
            description="Optional. Leave blank to auto-generate. No transactional email is sent — you'll get the password back in the next screen to share with the user."
            placeholder="(auto-generated)"
            leftSection={<IconKey size={14} />}
            rightSection={
              <Tooltip label="Generate a strong password">
                <ActionIcon
                  variant="subtle"
                  onClick={() => form.setFieldValue("initial_password", generateReadablePassword())}
                >
                  <IconRefresh size={14} />
                </ActionIcon>
              </Tooltip>
            }
            {...form.getInputProps("initial_password")}
          />
          <Button type="submit" loading={invite.isPending} fullWidth mt="sm">
            Invite
          </Button>
        </Stack>
      </form>
    </Modal>
  );
}
