import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const ACCESS_TOKEN_KEY = 'auth.accessToken';
const REFRESH_TOKEN_KEY = 'auth.refreshToken';

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
  refreshToken: string;
};

export async function saveSession(session: Session): Promise<void> {
  await storage.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  await storage.setItem(REFRESH_TOKEN_KEY, session.refreshToken);
}

export async function getSession(): Promise<Session | null> {
  const [accessToken, refreshToken] = await Promise.all([
    storage.getItem(ACCESS_TOKEN_KEY),
    storage.getItem(REFRESH_TOKEN_KEY),
  ]);

  // 둘 중 하나라도 없으면 세션이 없는 것으로 취급
  if (!accessToken || !refreshToken) return null;
  return { accessToken, refreshToken };
}

export async function clearSession(): Promise<void> {
  await Promise.all([storage.removeItem(ACCESS_TOKEN_KEY), storage.removeItem(REFRESH_TOKEN_KEY)]);
}
