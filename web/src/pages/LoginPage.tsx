import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, LoaderCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { ApiError, loginAdmin } from "@/lib/api";
import {
  clearSession, saveSession, SessionExpiredError, SESSION_EXPIRED_MESSAGE, useAuthStore,
} from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const loginSchema = z.object({
  username: z.string().min(1, "Vui lòng nhập tên đăng nhập."),
  password: z.string().min(1, "Vui lòng nhập mật khẩu."),
});
type LoginValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const status = useAuthStore((state) => state.status);
  const [error, setError] = useState("");
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit(values: LoginValues) {
    setError("");
    clearSession();
    queryClient.clear();
    try {
      const session = await loginAdmin(values.username, values.password);
      saveSession(session);
      navigate("/", { replace: true });
    } catch (cause) {
      if (cause instanceof SessionExpiredError) setError(SESSION_EXPIRED_MESSAGE);
      else if (cause instanceof ApiError) setError(cause.message);
      else setError("Không thể hoàn tất đăng nhập. Vui lòng thử lại.");
    } finally {
      form.resetField("password");
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex items-center justify-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Activity className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold">Log Anomaly Explorer</p>
            <p className="text-xs text-muted-foreground">AI-06 · SE2026-T04</p>
          </div>
        </div>
        <Card>
          <CardHeader className="gap-2">
            <h1 className="text-xl font-semibold">Đăng nhập quản trị</h1>
            <CardDescription>Đăng nhập để tra cứu log và theo dõi các cụm bất thường.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate aria-busy={isSubmitting} className="space-y-4">
              {status === "expired" && !error && (
                <p role="status" className="rounded-lg border bg-muted px-3 py-2 text-sm">
                  {SESSION_EXPIRED_MESSAGE}
                </p>
              )}
              {error && (
                <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="username">Tên đăng nhập</Label>
                <Input id="username" autoComplete="username" autoCapitalize="none" spellCheck={false}
                  disabled={isSubmitting} aria-invalid={Boolean(errors.username)}
                  aria-describedby={errors.username ? "username-error" : undefined}
                  {...form.register("username")} />
                {errors.username && <p id="username-error" className="text-xs text-destructive">{errors.username.message}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Mật khẩu</Label>
                <Input id="password" type="password" autoComplete="current-password"
                  disabled={isSubmitting} aria-invalid={Boolean(errors.password)}
                  aria-describedby={errors.password ? "password-error" : undefined}
                  {...form.register("password")} />
                {errors.password && <p id="password-error" className="text-xs text-destructive">{errors.password.message}</p>}
              </div>
              <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>
                {isSubmitting && <LoaderCircle className="animate-spin" aria-hidden="true" />}
                {isSubmitting ? "Đang đăng nhập..." : "Đăng nhập"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="text-center text-xs text-muted-foreground">Dành cho tài khoản quản trị đã được cấp.</p>
      </div>
    </main>
  );
}
