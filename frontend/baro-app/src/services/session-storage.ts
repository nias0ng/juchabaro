/** 로그인 세션(accessToken)을 저장/조회/삭제한다. 웹은 SecureStore를 지원하지 않아 AsyncStorage를 대신 쓴다. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const ACCESS_TOKEN_KEY = 'auth.accessToken';
const LEGACY_REFRESH_TOKEN_KEY = 'auth.refreshToken';

const isWeb = Platform.OS === 'web';

const storage = {
  getItem: (key: string) => (isWeb ? AsyncStorage.getItem(key) : SecureStore.getItemAsync(key)),
  setItem: (key: string, value: string) =>
    isWeb ? AsyncStorage.setItem(key, value) : SecureStore.setItemAsync(key, value),
  removeItem: (key: string) =>
    isWeb ? AsyncStorage.removeItem(key) : SecureStore.deleteItemAsync(key),
};

export type Session = {
  accessToken: string;
};

export async function saveSession(session: Session): Promise<void> {
  await Promise.all([
    storage.setItem(ACCESS_TOKEN_KEY, session.accessToken),
    storage.removeItem(LEGACY_REFRESH_TOKEN_KEY),
  ]);
}

export async function getSession(): Promise<Session | null> {
  const accessToken = await storage.getItem(ACCESS_TOKEN_KEY);

  if (!accessToken) return null;
  return { accessToken };
}

export async function clearSession(): Promise<void> {
  await Promise.all([
    storage.removeItem(ACCESS_TOKEN_KEY),
    storage.removeItem(LEGACY_REFRESH_TOKEN_KEY),
  ]);
}
