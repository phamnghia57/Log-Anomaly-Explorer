import { useEffect, useSyncExternalStore } from "react";
import { getSession, useAuthStore } from "@/lib/auth";

function readActiveSession() {
  const session = useAuthStore.getState().session;
  return session && Date.parse(session.expires_at) > Date.now() ? session : null;
}

export function useAuthSession() {
  const session = useSyncExternalStore(useAuthStore.subscribe, readActiveSession);
  // Snapshot khong coi phien het han la authenticated, ke ca timer o tab nen chua chay.
  // Viec xoa state/storage duoc thuc hien sau render.
  useEffect(() => { getSession(); }, [session]);
  return session;
}
