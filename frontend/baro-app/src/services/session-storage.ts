// AsyncStorage(아이디 저장에 쓴 것)와 달리, SecureStore는 기기의 암호화 저장소를 쓴다.
// accessToken/refreshToken은 유출되면 남의 계정으로 로그인당할 수 있는 민감한 값이라
// 평문으로 저장되는 AsyncStorage 대신 이걸 쓴다.
//
// 다만 expo-secure-store는 웹에서 실제 구현이 없다(브라우저엔 Keychain/Keystore 같은 게 없어서).
// 그래서 웹에서만 AsyncStorage로 대체한다 — 웹은 원래 브라우저 저장소 자체가
// 네이티브의 보안 수준을 못 따라가므로, 이 대체가 새로운 약점을 만드는 건 아니다.
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

  // 둘 중 하나라도 없으면 세션이 없는 것으로 취급한다 (반쪽짜리 세션은 의미가 없다).
  if (!accessToken || !refreshToken) return null;
  return { accessToken, refreshToken };
}

export async function clearSession(): Promise<void> {
  await Promise.all([storage.removeItem(ACCESS_TOKEN_KEY), storage.removeItem(REFRESH_TOKEN_KEY)]);
}
