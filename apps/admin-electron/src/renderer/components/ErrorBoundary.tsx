import React from "react";
import { Alert, Button, Code, Stack, Text } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("ErrorBoundary caught", error, info);
  }

  reset = () => this.setState({ error: null });

  override render(): React.ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <Stack
        align="center"
        justify="center"
        h="100vh"
        p="xl"
        bg="dark.8"
        gap="md"
      >
        <Alert
          icon={<IconAlertTriangle />}
          title="Something went wrong in the renderer."
          color="red"
          maw={720}
        >
          <Text size="sm" mb="sm">
            The view crashed. Reload the window — if it keeps happening, file an
            issue with the details below.
          </Text>
          <Code block>{this.state.error.stack ?? this.state.error.message}</Code>
        </Alert>
        <Button onClick={this.reset}>Reset view</Button>
        <Button variant="subtle" onClick={() => window.location.reload()}>
          Reload window
        </Button>
      </Stack>
    );
  }
}
