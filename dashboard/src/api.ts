export interface ApiErrorPayload {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  details: Record<string, unknown> | null;

  constructor(status: number, payload?: ApiErrorPayload) {
    super(payload?.message || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = payload?.code ?? null;
    this.details = payload?.details ?? null;
  }
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers || {}),
    },
  });

  const parsed = await parseResponseBody(response);
  if (!response.ok) {
    const payload = typeof parsed === "object" && parsed !== null && "error" in parsed
      ? (parsed as { error?: ApiErrorPayload }).error
      : undefined;
    throw new ApiError(response.status, payload);
  }

  return parsed as T;
}

export async function fetchJson<T>(url: string): Promise<T> {
  return requestJson<T>(url);
}

export async function putJson<T>(url: string, payload: unknown): Promise<T> {
  return requestJson<T>(url, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
