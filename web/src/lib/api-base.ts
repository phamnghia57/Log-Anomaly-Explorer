// Resolve /api relative to the page; auth cookies stay on the web origin.
export const API_BASE_URL = new URL(
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "/api",
  window.location.origin,
).href.replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}
