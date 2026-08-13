/**
 * Browser-side API client — STATIC SPA build.
 *
 * Talks DIRECTLY to the serverless API Gateway (AWS) with the opaque
 * session token from `session-store` as `Authorization: Bearer <token>`.
 * No /api/proxy, no cookies, no middleware — all of that gone in the
 * static export.
 *
 * Method surface mirrors the old server-side `createApiClient` so pages
 * (dashboard, twin, alerts, …) work unchanged. Routes the serverless
 * stack doesn't implement (/alerts, /sensors, /work-orders,
 * /building/snapshot) resolve to 404 → ApiError('not_found'), which
 * pages already treat as a degraded-but-graceful state.
 */
import { getClientEnv } from '@/env';
import { ApiError, type ApiErrorCode } from './api-client';
import type { Building, Asset, Sensor, SensorReading, Alert, WorkOrder } from './api-client';
import { getToken, setSession, clearSession, type SessionData } from './session-store';

function codeForStatus(status: number): { code: ApiErrorCode; message: string } {
  if (status === 0 || status === 502 || status === 503 || status === 504) {
    return { code: 'network_unavailable', message: 'The service is temporarily unreachable.' };
  }
  if (status === 401) return { code: 'unauthorized', message: 'Your session has expired. Please sign in again.' };
  if (status === 403) return { code: 'forbidden', message: 'You do not have permission to perform this action.' };
  if (status === 404) return { code: 'not_found', message: 'The requested resource was not found.' };
  if (status === 429) return { code: 'rate_limited', message: 'Too many requests. Please try again shortly.' };
  if (status >= 400 && status < 500) return { code: 'validation_error', message: 'The request was invalid.' };
  return { code: 'upstream_error', message: 'The service returned an error. Please try again.' };
}

function unwrap<T>(body: unknown, key: string): T {
  if (body && typeof body === 'object' && key in (body as Record<string, unknown>)) {
    return (body as Record<string, T>)[key];
  }
  return body as T;
}

/**
 * The serverless data API wraps collections in a key (`{assets:[…]}`,
 * `{buildings:[…]}`). The old api-gateway returned bare arrays.
 * Auto-unwrap the first array-valued key so page callers keep working.
 */
function unwrapAnyArray(body: unknown): unknown {
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const obj = body as Record<string, unknown>;
    for (const key of ['assets', 'buildings', 'readings', 'files', 'alerts', 'sensors', 'workOrders']) {
      if (Array.isArray(obj[key])) return obj[key];
    }
  }
  return body;
}

function buildUrl(path: string): string {
  const base = getClientEnv().apiBaseUrl.replace(/\/$/, '');
  // Auth + AI routes live at the gateway ROOT; data routes at /api/*.
  if (path.startsWith('/auth/') || path === '/auth') return `${base}${path}`;
  return `${base}/api${path.startsWith('/') ? path : `/${path}`}`;
}

export interface BrowserApiClientOptions {
  signal?: AbortSignal;
}

export function createBrowserApiClient(opts: BrowserApiClientOptions = {}) {
  async function call<T>(
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: string,
    body?: unknown,
    unwrapKey?: string,
  ): Promise<T> {
    const init: RequestInit = {
      method,
      headers: { 'content-type': 'application/json' } as Record<string, string>,
    };
    const token = getToken();
    if (token) {
      (init.headers as Record<string, string>)['authorization'] = `Bearer ${token}`;
    }
    if (opts.signal) init.signal = opts.signal;
    if (body !== undefined) init.body = JSON.stringify(body);

    let res: Response;
    try {
      res = await fetch(buildUrl(path), init);
    } catch (e) {
      throw new ApiError('network_unavailable', 0, 'The service is temporarily unreachable.', e);
    }

    if (!res.ok) {
      let upstreamBody: unknown = undefined;
      try {
        upstreamBody = await res.text();
      } catch {
        /* ignore */
      }
      const { code, message } = codeForStatus(res.status);
      // eslint-disable-next-line no-console
      console.error(`[browser-api] ${res.status} ${code} on ${method} ${path}:`, upstreamBody);
      if (code === 'unauthorized') clearSession();
      throw new ApiError(code, res.status, message, upstreamBody);
    }

    const text = await res.text();
    if (!text) return undefined as T;
    const parsed = JSON.parse(text);
    if (unwrapKey) return unwrap<T>(parsed, unwrapKey);
    return unwrapAnyArray(parsed) as T;
  }

  function qs(params: Record<string, string | number | undefined | null>): string {
    const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
    if (!entries.length) return '';
    return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&');
  }

  return {
    // ───── Serverless auth (OTP flow, gateway root — NOT under /api) ─────
    requestOtp: (email: string) =>
      call<{ message?: string; requiresOTP?: boolean }>('POST', '/auth/login', { email }),
    register: (input: { email: string; name: string; mobile?: string }) =>
      call<{ message?: string; requiresOTP?: boolean }>('POST', '/auth/register', input),
    verifyOtp: async (email: string, otp: string): Promise<SessionData> => {
      const body = await call<{ token: string; user?: { email?: string; name?: string } }>(
        'POST',
        '/auth/verify',
        { email, otp },
      );
      const session: SessionData = {
        token: body.token,
        email: body.user?.email ?? email,
        name: body.user?.name,
      };
      setSession(session);
      return session;
    },
    clearSession,

    // ───── Buildings (serverless: GET /api/buildings → {buildings:[…]}) ─────
    findBuildings: () => call<Building[]>('GET', '/buildings', undefined, 'buildings'),
    findBuilding: (id: string): Promise<Building> => call<Building>('GET', `/buildings/${id}`),
    findBuildingFloors: (..._args: unknown[]): Promise<unknown[]> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    updateZone: (..._args: unknown[]): Promise<unknown> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    findBuildingSnapshot: (..._args: unknown[]): Promise<{ found: false; snapshot: null; message: string }> =>
      Promise.resolve({ found: false, snapshot: null, message: 'Snapshots are server-only in the serverless build.' }),
    findBuildingSnapshotHistory: (..._args: unknown[]) => Promise.resolve({ history: [] }),

    // ───── Assets (serverless: GET /api/assets → {assets:[…]}) ─────
    findAssets: (filter: Record<string, unknown> = {}): Promise<Asset[]> =>
      call<Asset[]>(
        'GET',
        `/assets${qs(filter as Record<string, string | number | undefined | null>)}`,
        undefined,
        'assets',
      ),
    findAsset: (id: string): Promise<Asset> => call<Asset>('GET', `/assets/${id}`),

    // ───── Sensors / readings — not exposed by the serverless stack ─────
    findSensors: (..._args: unknown[]): Promise<Sensor[]> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    findSensor: (..._args: unknown[]): Promise<Sensor> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    findReadings: (..._args: unknown[]): Promise<SensorReading[]> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },

    // ───── Alerts / work orders — not exposed by the serverless stack ─────
    findAlerts: (..._args: unknown[]): Promise<Alert[]> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    findAlert: (..._args: unknown[]): Promise<Alert> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    acknowledgeAlert: (..._args: unknown[]): Promise<unknown> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    resolveAlert: (..._args: unknown[]): Promise<unknown> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    findWorkOrders: (..._args: unknown[]): Promise<WorkOrder[]> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    createWorkOrder: (..._args: unknown[]): Promise<unknown> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },
    updateWorkOrder: (..._args: unknown[]): Promise<unknown> => {
      const err = new ApiError('not_found', 404, 'The requested resource was not found.');
      return Promise.reject(err);
    },

    // ───── Profile (serverless: GET /api/me) ─────
    me: () => call<{ email: string; name?: string; created_at?: string }>('GET', '/me'),

    // ───── Generic verb surface (kept for page callers) ─────
    get: <T>(path: string) => call<T>('GET', path),
    post: <T>(path: string, body?: unknown) => call<T>('POST', path, body),
    put: <T>(path: string, body?: unknown) => call<T>('PUT', path, body),
    patch: <T>(path: string, body?: unknown) => call<T>('PATCH', path, body),
    delete: <T>(path: string) => call<T>('DELETE', path),
  };
}

export type BrowserApiClient = ReturnType<typeof createBrowserApiClient>;