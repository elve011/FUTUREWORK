export type AuthUser = {
  id: number;
  email: string;
  display_name: string;
  role: "FREELANCER" | "CLIENT" | "ADMIN";
  status: "ACTIVE" | "SUSPENDED";
  github_login: string;
  demo_only: boolean;
};

type AuthResponse = { user?: AuthUser; detail?: unknown; error?: string; csrf_token?: string };

async function readJson(response: Response): Promise<AuthResponse> {
  return response.json().catch(() => ({}));
}

export async function postWithCsrf(url: string, payload: Record<string, unknown>) {
  const csrfResponse = await fetch("/backend-api/auth/csrf", { credentials: "include", cache: "no-store" });
  const csrfBody = await readJson(csrfResponse);
  if (!csrfResponse.ok || !csrfBody.csrf_token) throw new Error("Impossible d’obtenir le jeton CSRF. Recharge la page et réessaie.");

  const response = await fetch(url,
    {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfBody.csrf_token },
    body: JSON.stringify(payload),
    },
  );
  const body = await readJson(response);
  if (!response.ok) {
    const details = body.detail ?? body.error ?? "La demande a échoué.";
    throw new Error(typeof details === "string" ? details : JSON.stringify(details));
  }
  return body;
}

export function postAuth(path: "login" | "signup" | "logout", payload: Record<string, string> = {}) {
  return postWithCsrf(`/backend-api/auth/${path}`, payload);
}
