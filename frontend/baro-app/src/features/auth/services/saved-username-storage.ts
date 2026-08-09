import AsyncStorage from '@react-native-async-storage/async-storage';

/** 로그인 화면의 "아이디 저장" 체크박스에 쓰는 아이디를 AsyncStorage에 저장/조회/삭제한다. */
const SAVED_USERNAME_KEY = 'auth.savedUsername';

export async function getSavedUsername(): Promise<string | null> {
  return AsyncStorage.getItem(SAVED_USERNAME_KEY);
}

export async function setSavedUsername(username: string): Promise<void> {
  await AsyncStorage.setItem(SAVED_USERNAME_KEY, username);
}

export async function clearSavedUsername(): Promise<void> {
  await AsyncStorage.removeItem(SAVED_USERNAME_KEY);
}
