import { useState } from 'react';

import type { NotificationChannel, NotificationSettings } from '@/features/profile/api/types';

// TODO(profile-api): PATCH /users/me/notification-settings가 준비되면 조회/저장을 실제 API로 교체한다.
const DEFAULT_SETTINGS: NotificationSettings = {
  moveRequestReceive: true,
  responseReminder: true,
  evOverstay: true,
  officeNotice: false,
  quietHoursStart: '23:00',
  quietHoursEnd: '07:00',
  channel: 'PUSH',
};

export function useNotificationSettings() {
  const [settings, setSettings] = useState<NotificationSettings>(DEFAULT_SETTINGS);

  const setResponseReminder = (value: boolean) =>
    setSettings((prev) => ({ ...prev, responseReminder: value }));
  const setEvOverstay = (value: boolean) => setSettings((prev) => ({ ...prev, evOverstay: value }));
  const setOfficeNotice = (value: boolean) => setSettings((prev) => ({ ...prev, officeNotice: value }));
  const setChannel = (value: NotificationChannel) => setSettings((prev) => ({ ...prev, channel: value }));
  const setQuietHoursStart = (value: string) => setSettings((prev) => ({ ...prev, quietHoursStart: value }));
  const setQuietHoursEnd = (value: string) => setSettings((prev) => ({ ...prev, quietHoursEnd: value }));

  return {
    settings,
    setResponseReminder,
    setEvOverstay,
    setOfficeNotice,
    setChannel,
    setQuietHoursStart,
    setQuietHoursEnd,
  };
}
