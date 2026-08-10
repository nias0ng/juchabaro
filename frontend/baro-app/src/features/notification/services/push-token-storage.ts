import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type { PushTokenRegistration } from './push-token';

/** 마지막으로 서버에 등록한 푸시 토큰을 SecureStore에 저장/조회/삭제한다(웹은 no-op). */
const PUSH_TOKEN_REGISTRATION_KEY = 'notification.pushTokenRegistration';

export async function savePushTokenRegistration(
  registration: PushTokenRegistration,
): Promise<void> {
  if (Platform.OS === 'web') return;

  await SecureStore.setItemAsync(PUSH_TOKEN_REGISTRATION_KEY, JSON.stringify(registration));
}

export async function getStoredPushTokenRegistration(): Promise<PushTokenRegistration | null> {
  if (Platform.OS === 'web') return null;

  const storedValue = await SecureStore.getItemAsync(PUSH_TOKEN_REGISTRATION_KEY);
  if (!storedValue) return null;

  try {
    const registration = JSON.parse(storedValue) as Partial<PushTokenRegistration>;
    if (
      typeof registration.token !== 'string' ||
      (registration.platform !== 'ANDROID' && registration.platform !== 'IOS')
    ) {
      return null;
    }

    return {
      token: registration.token,
      platform: registration.platform,
    };
  } catch {
    return null;
  }
}

export async function clearStoredPushTokenRegistration(): Promise<void> {
  if (Platform.OS === 'web') return;

  await SecureStore.deleteItemAsync(PUSH_TOKEN_REGISTRATION_KEY);
}
