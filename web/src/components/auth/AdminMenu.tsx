import { ChevronDown, LogIn, LogOut, ShieldUser } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { clearSession } from "@/lib/auth";
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

  function logout() {
    clearSession();
    queryClient.clear();
    navigate("/login", { replace: true });
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
        <DropdownMenuItem onSelect={logout}>
          <LogOut aria-hidden="true" /> Đăng xuất
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
