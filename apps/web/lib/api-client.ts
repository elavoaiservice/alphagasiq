const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export async function apiGet<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiMutate<T>("POST", path, body, token);
}

export async function apiPut<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiMutate<T>("PUT", path, body, token);
}

export async function apiPatch<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiMutate<T>("PATCH", path, body, token);
}

async function apiMutate<T>(
  method: "POST" | "PUT" | "PATCH",
  path: string,
  body: unknown,
  token?: string
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json())?.detail ?? "";
    } catch {
      // response body wasn't JSON -- fall through with the bare status
    }
    throw new Error(`${method} ${path} failed: ${res.status}${detail ? ` — ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export { API_BASE };
