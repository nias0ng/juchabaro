import { getJson } from '@/services/http-client';

import type { NotificationListResult } from './types';

export function getNotifications(accessToken: string): Promise<NotificationListResult> {
  return getJson<NotificationListResult>('/api/notifications?size=50', accessToken);
}
