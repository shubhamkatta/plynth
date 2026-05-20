import { createTheme, MantineColorsTuple } from "@mantine/core";

const brand: MantineColorsTuple = [
  "#eef2ff",
  "#dbe1ff",
  "#b3bcff",
  "#8896ff",
  "#6675ff",
  "#5160ff",
  "#4753ff",
  "#3a44e5",
  "#323bcc",
  "#2731b3",
];

export const theme = createTheme({
  primaryColor: "brand",
  colors:       { brand },
  fontFamily:   "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  defaultRadius: "md",
  cursorType: "pointer",
  components: {
    Button: { defaultProps: { fw: 600 } },
    Card:   { defaultProps: { withBorder: true, padding: "lg", radius: "md" } },
    Modal:  { defaultProps: { centered: true, radius: "md", overlayProps: { blur: 2 } } },
  },
});
