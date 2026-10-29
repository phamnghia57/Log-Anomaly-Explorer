import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AUTH_STORAGE_KEY, getSession, restoreSession, useAuthStore } from "@/lib/auth";

export function AuthSessionManager({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  useEffect(() => {
    // clear() huy query dang chay va xoa ca query/mutation cache khi doi phien.
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.session?.token !== previous.session?.token) queryClient.clear();
    });
    if (!getSession()) queryClient.clear();
    const syncStorage = (event: StorageEvent) => {
      if (event.key === AUTH_STORAGE_KEY || event.key === null) restoreSession();
    };
    const checkExpiration = () => { getSession(); };
    window.addEventListener("storage", syncStorage);
    window.addEventListener("focus", checkExpiration);
    document.addEventListener("visibilitychange", checkExpiration);
    return () => {
      unsubscribe();
      window.removeEventListener("storage", syncStorage);
      window.removeEventListener("focus", checkExpiration);
      document.removeEventListener("visibilitychange", checkExpiration);
    };
  }, [queryClient]);

  return children;
}
