import { Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/pages/DashboardPage";
import { SearchPage } from "@/pages/SearchPage";
import { ClusterDetailPage } from "@/pages/ClusterDetailPage";
import { LoginPage } from "@/pages/LoginPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<DashboardPage />} />
      <Route path="/search" element={<SearchPage />} />
      <Route path="/clusters/:id" element={<ClusterDetailPage />} />
    </Routes>
  );
}
