import { useEffect, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getSession, refreshSession, restoreSession, startAuthSync, useAuthStore } from "@/lib/auth";

export function AuthSessionManager({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const status = useAuthStore((state) => state.status);

  useEffect(() => {
    // clear() huy query dang chay va xoa ca query/mutation cache khi doi phien.
    const unsubscribe = useAuthStore.subscribe((state, previous) => {
      if (state.generation !== previous.generation) queryClient.clear();
    });
    if (!getSession()) queryClient.clear();
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

  if (status === "initializing") return <main className="grid min-h-svh place-content-center" role="status">Đang kiểm tra phiên đăng nhập...</main>;
  if (status === "unavailable") return <main className="grid min-h-svh place-content-center gap-3 p-6">
    <p role="alert">Chưa xác minh được phiên đăng nhập. Vui lòng thử lại.</p>
    <button type="button" className="rounded border px-4 py-2" onClick={() => { void restoreSession().catch(() => {}); }}>Thử lại</button>
  </main>;
  return children;
}
