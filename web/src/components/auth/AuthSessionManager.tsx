import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSession, refreshSession, startAuthSync, useAuthStore } from "@/lib/auth";
import { SYSTEM_HEALTH_QUERY_KEY } from "@/lib/queries";

export function AuthSessionManager({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const clearPrivateCache = () => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== SYSTEM_HEALTH_QUERY_KEY[0] });
      queryClient.getMutationCache().clear();
    };
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.generation !== previous.generation) clearPrivateCache();
    });
    if (!getSession()) clearPrivateCache();
    const stopSync = startAuthSync();
    const checkExpiration = () => {
      const session = getSession();
      if (session && Date.parse(session.expires_at) <= Date.now()) void refreshSession().catch(() => {});
    };
    window.addEventListener("focus", checkExpiration);
    document.addEventListener("visibilitychange", checkExpiration);
    return () => {
      unsubscribe();
      stopSync();
      window.removeEventListener("focus", checkExpiration);
      document.removeEventListener("visibilitychange", checkExpiration);
    };
  }, [queryClient]);

  return children;
}
