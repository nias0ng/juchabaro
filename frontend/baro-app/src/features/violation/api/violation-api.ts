/** 위반 통계 API 래퍼. */
import { getJson } from '@/services/http-client';

import type { ViolationStats } from './types';

/** GET /api/move-requests/stats — 이동 요청 기반 위반 통계를 조회한다. */
export function getViolationStats(accessToken: string): Promise<ViolationStats> {
  return getJson<ViolationStats>('/api/move-requests/stats', accessToken);
}
