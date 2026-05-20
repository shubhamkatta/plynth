import { Group, Stack, Text, Title } from "@mantine/core";

interface Props {
  title:        string;
  description?: string;
  actions?:     React.ReactNode;
}

export function PageHeader({ title, description, actions }: Props) {
  return (
    <Group justify="space-between" align="flex-end" mb="lg" wrap="nowrap">
      <Stack gap={4}>
        <Title order={2}>{title}</Title>
        {description && <Text c="dimmed" size="sm">{description}</Text>}
      </Stack>
      {actions && <Group gap="sm">{actions}</Group>}
    </Group>
  );
}
