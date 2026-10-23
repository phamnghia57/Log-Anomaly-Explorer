import { format, formatDistanceToNow } from "date-fns";
import { vi } from "date-fns/locale";

export function formatDateTime(ts: string): string {
  try {
    return format(new Date(ts), "dd/MM/yyyy HH:mm:ss");
  } catch {
    return ts;
  }
}

export function formatRelative(ts: string): string {
  try {
    return formatDistanceToNow(new Date(ts), { addSuffix: true, locale: vi });
  } catch {
    return ts;
  }
}
