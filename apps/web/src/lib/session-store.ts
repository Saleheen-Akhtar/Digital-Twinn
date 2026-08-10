/**
 * Client-side session store for the static SPA.
 *
 * The serverless stack authenticates with an OTP → opaque session token
 * (see aws/lambda/auth.py). There is no JWT cookie and no middleware in
 * the static export, so the token lives in localStorage and is attached
 * as `Authorization: Bearer <token>` to every API call by
 * `browser-api-client`.
 *
 * Security notes (honest limits of a static SPA):
 * - localStorage is readable by any JS on the origin. We mitigate by
 *   keeping the token opaque, short-lived-ish, and revocable server-side
 *   (users table row).
 * - XSS would exfiltrate it — no different from any SPA with a bearer
 *   token (e.g. GitHub's classic token flow).
 */

export interface SessionData {
  token: string;
  email: string;
  name?: string;
}

const STORAGE_KEY = 'dtfm_session';

function read(): SessionData | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SessionData;
    if (!parsed || typeof parsed.token !== 'string' || parsed.token.length === 0) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function getSession(): SessionData | null {
  if (typeof window === 'undefined') return null;
  return read();
}

export function getToken(): string | null {
  return getSession()?.token ?? null;
}

export function setSession(session: SessionData): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(STORAGE_KEY);
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}