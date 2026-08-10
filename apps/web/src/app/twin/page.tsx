'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { createBrowserApiClient } from '@/lib/browser-api-client';
import { getSession } from '@/lib/session-store';
import type { Asset } from '@/lib/api-client';
import { DigitalTwinClient } from './client';

export default function DigitalTwinPage() {
  const router = useRouter();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!getSession()) {
      router.replace('/login/');
      return;
    }
    const api = createBrowserApiClient();
    api
      .findAssets()
      .then((list) => setAssets(list as Asset[]))
      .catch((err) => setLoadError(err instanceof Error ? err.message : 'Failed to load assets'));
  }, [router]);

  if (!getSession()) return null; // redirecting

  return <DigitalTwinClient initialAssets={assets} initialError={loadError} />;
}