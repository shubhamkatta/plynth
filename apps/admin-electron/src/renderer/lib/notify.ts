import { notifications } from "@mantine/notifications";
import { describeError } from "@renderer/lib/api";

export const notify = {
  success(title: string, message?: string) {
    notifications.show({ title, message, color: "teal", autoClose: 3500 });
  },
  info(title: string, message?: string) {
    notifications.show({ title, message, color: "blue", autoClose: 4000 });
  },
  warn(title: string, message?: string) {
    notifications.show({ title, message, color: "yellow", autoClose: 5000 });
  },
  error(title: string, err: unknown) {
    notifications.show({
      title,
      message:   describeError(err),
      color:     "red",
      autoClose: 7000,
    });
  },
};
