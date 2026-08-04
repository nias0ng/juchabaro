import { getJson } from '@/services/http-client';

import type { ViolationStats } from './types';

export function getViolationStats(accessToken: string): Promise<ViolationStats> {
  return getJson<ViolationStats>('/api/move-requests/stats', accessToken);
}
