/** 알림 수신 설정 API 래퍼. */
import { getJson, patchJson } from '@/services/http-client';

import type { NotificationSettings, UpdateNotificationSettingsRequest } from './types';

const NOTIFICATION_SETTINGS_PATH = '/api/users/me/notification-settings';

/** GET /api/users/me/notification-settings — 내 알림 수신 설정을 조회한다. */
export function getNotificationSettings(accessToken: string): Promise<NotificationSettings> {
  return getJson<NotificationSettings>(NOTIFICATION_SETTINGS_PATH, accessToken);
}

/** PATCH /api/users/me/notification-settings — 알림 수신 설정을 변경한다. */
export function updateNotificationSettings(
  request: UpdateNotificationSettingsRequest,
  accessToken: string,
): Promise<NotificationSettings> {
  return patchJson<NotificationSettings>(NOTIFICATION_SETTINGS_PATH, request, accessToken);
}
