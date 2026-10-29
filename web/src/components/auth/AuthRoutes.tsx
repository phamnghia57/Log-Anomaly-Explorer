import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthSession } from "@/hooks/use-auth-session";
import { safeReturnTo } from "@/lib/auth-navigation";

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
