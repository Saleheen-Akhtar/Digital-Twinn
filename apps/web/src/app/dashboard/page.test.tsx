import { render, screen, waitFor } from '@testing-library/react';
import DashboardPage from './page';

// Client-only page: session from localStorage-backed store, data via the
// browser API client, navigation via next/navigation. Mock all three.
jest.mock('@/lib/session-store', () => ({
  getSession: () => ({ token: 'mock-token', email: 'admin@dtfm.local', name: 'Admin' }),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), refresh: jest.fn(), prefetch: jest.fn(), back: jest.fn(), forward: jest.fn() }),
}));

const baseBuildings = [
  { id: 'building-1', name: 'Singapore - Hall 1', address: '1 Convention Drive', totalFloors: 5 },
];
const baseAssets = [
  { id: 'asset-ahu', buildingId: 'building-1', floorId: 'floor-3', floorLevel: 3, name: 'AHU-301', type: 'ahu', status: 'critical' },
  { id: 'asset-temp', buildingId: 'building-1', floorId: 'floor-3', floorLevel: 3, name: 'Temp Sensor 3A', type: 'sensor_only', status: 'warning' },
];

const noop = () => Promise.resolve([]);
const reject404 = () => Promise.reject(Object.assign(new Error('not_found'), { code: 'not_found', status: 404 }));

jest.mock('@/lib/browser-api-client', () => ({
  createBrowserApiClient: () => ({
    findBuildings: () => Promise.resolve(baseBuildings),
    findAssets: () => Promise.resolve(baseAssets),
    findSensors: reject404,
    findAlerts: reject404,
    findWorkOrders: reject404,
    findReadings: reject404,
    findBuildingSnapshot: () => Promise.resolve({ found: false }),
    findBuildingSnapshotHistory: () => Promise.resolve({ history: [] }),
    requestOtp: () => Promise.resolve({}),
    verifyOtp: () => Promise.resolve({}),
    me: () => Promise.resolve({ email: 'admin@dtfm.local', name: 'Admin' }),
    get: noop,
    post: noop,
    put: noop,
    patch: noop,
    delete: noop,
  }),
}));

describe('DashboardPage (static SPA)', () => {
  it('renders a loading state then the greeting with authenticated user', async () => {
    render(<DashboardPage />);
    expect(screen.getByText(/loading dashboard/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/Admin/)).toBeInTheDocument();
    });
  });

  it('shows the connection banner when data sources are unavailable (serverless subset)', async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId('connection-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('connection-banner-headline').textContent).toMatch(/failed/i);
  });
});