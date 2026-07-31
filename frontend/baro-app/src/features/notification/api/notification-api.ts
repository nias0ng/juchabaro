import { getJson } from '@/services/http-client';

import { getNotificationsMock } from './notification-api.mock';
import type { NotificationListResult } from './types';

const useMockNotification = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_NOTIFICATION === 'true';

export function getNotifications(accessToken: string): Promise<NotificationListResult> {
  if (useMockNotification) {
    return getNotificationsMock();
  }

  return getJson<NotificationListResult>('/notifications?size=50', accessToken);
}
