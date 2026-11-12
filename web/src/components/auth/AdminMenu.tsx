import { ChevronDown, LogIn, LogOut, ShieldUser } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { logoutSession } from "@/lib/auth";
import { useAuthSession } from "@/hooks/use-auth-session";
import { safeReturnTo } from "@/lib/auth-navigation";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function AdminMenu() {
  const session = useAuthSession();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function logout() {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      await logoutSession();
      queryClient.clear();
      navigate("/login", { replace: true });
    } catch {
      setError("Chưa xác nhận đăng xuất. Vui lòng thử lại.");
    } finally { setPending(false); }
  }

  if (!session) {
    return <Button asChild variant="outline" size="sm">
      <Link to="/login" state={{ from: safeReturnTo(`${location.pathname}${location.search}${location.hash}`) }}>
        <LogIn aria-hidden="true" /> Đăng nhập
      </Link>
    </Button>;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Menu quản trị">
          <ShieldUser aria-hidden="true" />
          <span className="hidden sm:inline">Quản trị viên</span>
          <ChevronDown aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Tài khoản admin</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={pending} onSelect={(event) => { event.preventDefault(); void logout(); }}>
          <LogOut aria-hidden="true" /> {pending ? "Đang đăng xuất..." : "Đăng xuất"}
        </DropdownMenuItem>
        {error && <p role="alert" className="max-w-64 px-2 py-1 text-sm text-destructive">{error}</p>}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
