import { Alert, Card, List, Stack, Text } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { PageHeader } from "@renderer/components/PageHeader";

interface Props {
  title:        string;
  description?: string;
  /** Bulleted list of what this page will do when implemented. */
  todo:         string[];
  /** Which platform endpoints this page will consume. */
  endpoints?:   string[];
}

export function StubPage({ title, description, todo, endpoints }: Props) {
  return (
    <Stack>
      <PageHeader title={title} description={description} />
      <Alert
        icon={<IconInfoCircle />}
        title="Coming next"
        color="brand"
        variant="light"
      >
        This view is scaffolded but not yet implemented. The contract below is
        what it will look like once we wire it. The platform API itself
        already supports these operations — see{" "}
        <Text component="span" ff="monospace" size="sm">docs/INTEGRATION.md</Text>.
      </Alert>

      <Card>
        <Text fw={600} mb="xs">Planned features</Text>
        <List size="sm">
          {todo.map(t => <List.Item key={t}>{t}</List.Item>)}
        </List>
      </Card>

      {endpoints && endpoints.length > 0 && (
        <Card>
          <Text fw={600} mb="xs">Platform endpoints used</Text>
          <List size="sm" listStyleType="none" spacing={4}>
            {endpoints.map(e => (
              <List.Item key={e}>
                <Text ff="monospace" size="sm">{e}</Text>
              </List.Item>
            ))}
          </List>
        </Card>
      )}
    </Stack>
  );
}
