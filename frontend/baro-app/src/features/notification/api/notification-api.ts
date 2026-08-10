/** 알림 목록 API 래퍼. */
import { getJson } from '@/services/http-client';

import type { NotificationListResult } from './types';

/** GET /api/notifications — 내 알림 목록을 최신순으로 조회한다(최대 50건). */
export function getNotifications(accessToken: string): Promise<NotificationListResult> {
  return getJson<NotificationListResult>('/api/notifications?size=50', accessToken);
}
