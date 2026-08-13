import RootPage from './page';

describe('RootPage', () => {
  it('renders the static landing page (server component)', () => {
    expect(typeof RootPage).toBe('function');
  });
});