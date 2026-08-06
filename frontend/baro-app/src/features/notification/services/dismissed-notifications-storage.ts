import AsyncStorage from '@react-native-async-storage/async-storage';

const DISMISSED_NOTIFICATION_IDS_KEY = 'notification.dismissedIds';

function parseDismissedIds(stored: string | null): Set<number> {
  if (!stored) return new Set();

  try {
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((id): id is number => typeof id === 'number'));
  } catch {
    return new Set();
  }
}

export async function getDismissedNotificationIds(): Promise<Set<number>> {
  const stored = await AsyncStorage.getItem(DISMISSED_NOTIFICATION_IDS_KEY);
  return parseDismissedIds(stored);
}

/** 스와이프로 숨긴 알림 id를 기기에 기록한다. 서버에는 반영되지 않아 다른 기기/재설치 후에는 다시 보인다. */
export async function addDismissedNotificationId(notificationId: number): Promise<void> {
  const ids = await getDismissedNotificationIds();
  ids.add(notificationId);
  await AsyncStorage.setItem(DISMISSED_NOTIFICATION_IDS_KEY, JSON.stringify(Array.from(ids)));
}
