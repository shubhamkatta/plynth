import { useEffect, useState } from "react";
import { Alert, Button, Group, Modal, Stack, Text, TextInput } from "@mantine/core";
import { IconAlertCircle, IconCalendarOff } from "@tabler/icons-react";

import { useUpdateTenant } from "@renderer/features/tenants/useTenants";
import { notify } from "@renderer/lib/notify";
import type { Tenant } from "@shared/types";

interface Props {
  tenant: Tenant | null;
  onClose: () => void;
}

/** Compact admin override for tenant.expires_at. Hard cap on access —
 *  when set in the past, every user in this tenant + children gets 403. */
export function TenantExpiryModal({ tenant, onClose }: Props) {
  const update = useUpdateTenant();
  // datetime-local needs a value without timezone (YYYY-MM-DDTHH:mm).
  const [value, setValue] = useState("");

  useEffect(() => {
    if (tenant?.expires_at) {
      const d = new Date(tenant.expires_at);
      const pad = (n: number) => String(n).padStart(2, "0");
      setValue(
        `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
        `T${pad(d.getHours())}:${pad(d.getMinutes())}`,
      );
    } else {
      setValue("");
    }
  }, [tenant?.id, tenant?.expires_at]);

  if (!tenant) return null;

  const save = async (newExpiresAt: string | null) => {
    try {
      await update.mutateAsync({
        id: tenant.id,
        payload: { expires_at: newExpiresAt },
      });
      notify.success(
        "Tenant expiry updated",
        newExpiresAt ? new Date(newExpiresAt).toLocaleString() : "No expiry (no cap)",
      );
      onClose();
    } catch (e) {
      notify.error("Update failed", e);
    }
  };

  const expiresInPast = tenant.expires_at && new Date(tenant.expires_at) < new Date();

  return (
    <Modal opened={!!tenant} onClose={onClose} title={`Expiry for ${tenant.name}`} centered>
      <Stack>
        {expiresInPast && (
          <Alert color="red" icon={<IconAlertCircle />} title="Tenant access is currently denied">
            Users in this tenant (and any child tenants) can't sign in until you extend or clear the cap.
          </Alert>
        )}

        <Text size="sm" c="dimmed">
          Hard cap on this tenant's access. When set in the past, every authenticated
          call from any user inside (and any child tenant) is denied with 403. Clear
          to remove the cap; set a future date to extend a trial / lock-out.
        </Text>

        <TextInput
          label="Expires at"
          type="datetime-local"
          description="Your local timezone — converted to UTC on save."
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
        />

        <Group justify="space-between" mt="sm">
          <Button
            variant="subtle"
            color="gray"
            leftSection={<IconCalendarOff size={14} />}
            onClick={() => save(null)}
            disabled={!tenant.expires_at || update.isPending}
          >
            Clear (no cap)
          </Button>
          <Button
            onClick={() => save(value ? new Date(value).toISOString() : null)}
            loading={update.isPending}
            disabled={!value}
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
