import { Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/pages/DashboardPage";
import { SearchPage } from "@/pages/SearchPage";
import { ClusterDetailPage } from "@/pages/ClusterDetailPage";
import { LoginPage } from "@/pages/LoginPage";
import { AnonymousOnly, RequireAuth } from "@/components/auth/AuthRoutes";
import { AuthSessionManager } from "@/components/auth/AuthSessionManager";

export default function App() {
  return (
    <AuthSessionManager>
      <Routes>
        <Route path="/login" element={<AnonymousOnly><LoginPage /></AnonymousOnly>} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/clusters/:id" element={<ClusterDetailPage />} />
        </Route>
      </Routes>
    </AuthSessionManager>
  );
}
