// Chi quay lai cac route noi bo da biet; khong nhan URL ngoai hoac /login.
export function safeReturnTo(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")
    || /[\\\s]/.test(value)
    || Array.from(value).some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return "/";
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin
      || !(url.pathname === "/" || url.pathname === "/search" || /^\/clusters\/[^/]+$/.test(url.pathname))) return "/";
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/";
  }
}
