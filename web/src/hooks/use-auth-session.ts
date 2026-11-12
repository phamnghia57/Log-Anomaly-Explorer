import { useSyncExternalStore } from "react";
import { useAuthStore } from "@/lib/auth";

export function useAuthSession() {
  return useSyncExternalStore(useAuthStore.subscribe, () => useAuthStore.getState().session);
}
