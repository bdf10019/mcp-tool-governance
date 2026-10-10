function csrfToken(): string {
  const item = document.cookie
    .split("; ")
    .find((part) => part.startsWith("mcp_csrf="));
  return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
}

export class ApiError extends Error {
  code: string;
  status: number;
  nextAction?: string;

  constructor(code: string, message: string, status: number, nextAction?: string) {
    super(message);
    this.code = code;
    this.status = status;
    this.nextAction = nextAction;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if ((options.method ?? "GET").toUpperCase() !== "GET") {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error ?? {};
    throw new ApiError(
      error.code ?? "REQUEST_FAILED",
      error.message ?? "操作失敗",
      response.status,
      error.next_action,
    );
  }
  return payload as T;
}

