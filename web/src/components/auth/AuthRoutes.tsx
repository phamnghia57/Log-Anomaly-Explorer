import type { ReactNode } from "react";
import { Link, Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthSession } from "@/hooks/use-auth-session";
import { safeReturnTo } from "@/lib/auth-navigation";
import { restoreSession, useAuthStore } from "@/lib/auth";

export function AuthAvailability() {
  const status = useAuthStore((state) => state.status);
  if (status === "initializing") return <main className="grid min-h-svh place-content-center" role="status">Đang kiểm tra phiên đăng nhập...</main>;
  if (status === "unavailable") return <main className="grid min-h-svh place-content-center gap-3 p-6">
    <p role="alert">Chưa xác minh được phiên đăng nhập. Vui lòng thử lại.</p>
    <button type="button" className="rounded border px-4 py-2" onClick={() => { void restoreSession().catch(() => {}); }}>Thử lại</button>
    <Link to="/system-status" className="text-center underline">Trạng thái hệ thống</Link>
  </main>;
  return <Outlet />;
}

export function RequireAuth() {
  const session = useAuthSession();
  const location = useLocation();
  return session ? <Outlet /> : <Navigate to="/login" replace state={{
    from: safeReturnTo(`${location.pathname}${location.search}${location.hash}`),
  }} />;
}

export function AnonymousOnly({ children }: { children: ReactNode }) {
  const session = useAuthSession();
  const location = useLocation();
  const from = (location.state as { from?: unknown } | null)?.from;
  return session ? <Navigate to={safeReturnTo(from)} replace /> : children;
}
