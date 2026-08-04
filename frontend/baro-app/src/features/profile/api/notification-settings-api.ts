import { getJson, patchJson } from '@/services/http-client';

import type { NotificationSettings, UpdateNotificationSettingsRequest } from './types';

const NOTIFICATION_SETTINGS_PATH = '/api/users/me/notification-settings';

export function getNotificationSettings(accessToken: string): Promise<NotificationSettings> {
  return getJson<NotificationSettings>(NOTIFICATION_SETTINGS_PATH, accessToken);
}

export function updateNotificationSettings(
  request: UpdateNotificationSettingsRequest,
  accessToken: string,
): Promise<NotificationSettings> {
  return patchJson<NotificationSettings>(NOTIFICATION_SETTINGS_PATH, request, accessToken);
}
