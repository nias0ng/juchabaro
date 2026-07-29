import AsyncStorage from '@react-native-async-storage/async-storage';

/*
  아이디 저장소를 관리하는 서비스.
  async-storage : 브라우저의 localStorage와 비슷한 역할을 하는 저장소. 앱이 종료되어도 값이 유지 key-value 형태
*/
const SAVED_USERNAME_KEY = 'auth.savedUsername'; // 저장소에 아이디를 저장할 때 사용할 key 이름!

export async function getSavedUsername(): Promise<string | null> { // 저장소 접근은 시간이 걸릴 수 있기에 Promise를 반환하도록 async 함수로 만든다.
  return AsyncStorage.getItem(SAVED_USERNAME_KEY);
}

export async function setSavedUsername(username: string): Promise<void> {
  await AsyncStorage.setItem(SAVED_USERNAME_KEY, username);
}

export async function clearSavedUsername(): Promise<void> {
  await AsyncStorage.removeItem(SAVED_USERNAME_KEY);
}
