export const guestKeys = {
  all: ["guest-portal"] as const,
  info: (token: string) => [...guestKeys.all, "info", token] as const,
  checkin: (token: string) => [...guestKeys.all, "checkin", token] as const,
};
