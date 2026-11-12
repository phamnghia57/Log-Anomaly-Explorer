import { Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/pages/DashboardPage";
import { SearchPage } from "@/pages/SearchPage";
import { SystemStatusPage } from "@/pages/SystemStatusPage";
import { ClusterDetailPage } from "@/pages/ClusterDetailPage";
import { LoginPage } from "@/pages/LoginPage";
import { AnonymousOnly, AuthAvailability, RequireAuth } from "@/components/auth/AuthRoutes";
import { AuthSessionManager } from "@/components/auth/AuthSessionManager";

export default function App() {
  return (
    <AuthSessionManager>
      <Routes>
        <Route path="/system-status" element={<SystemStatusPage />} />
        <Route element={<AuthAvailability />}>
          <Route path="/login" element={<AnonymousOnly><LoginPage /></AnonymousOnly>} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/clusters/:id" element={<ClusterDetailPage />} />
          </Route>
        </Route>
      </Routes>
    </AuthSessionManager>
  );
}
