import { useCallback, useEffect, useState } from 'react';

import {
  clearSavedUsername,
  getSavedUsername,
  setSavedUsername,
} from '../services/saved-username-storage'; // 저장소 접근 함수들

/*
  아이디 저장소를 조회하고, 저장하고, 삭제하는 훅.
  - savedUsername: 저장소에 저장된 아이디 (없으면 null)
  - isLoaded: 저장소 조회가 끝났는지 여부
  - persistUsername(username): 아이디를 저장소에 저장
  - clearUsername(): 저장소에서 아이디 삭제
*/
export function useSavedUsername() {
  const [savedUsername, setSavedUsernameState] = useState<string | null>(null); // 저장소에서 읽어온 아이디값(없으면 null )
  const [isLoaded, setIsLoaded] = useState(false); // 저장소 읽기가 끝났는지 여부

  useEffect(() => {
  
    //isMounted: 조회가 끝나기 전에 화면 벗어나면 state를 건드리지 않게 함. 
    // -> 중간에 화면이 사라지면 setSavedUsernameState() 호출 시 에러가 나므로, isMounted 체크를 통해 방지한다.
    let isMounted = true; 
    // 저장소에서 name을 가져왔을 때, setSavedUsernameState(value)로 state를 바꾸면 화면이 다시 렌더링된다.
    getSavedUsername().then((value) => {
      if (!isMounted) return;
      setSavedUsernameState(value);
      setIsLoaded(true);
    });

    // 끝났으니까 이후 setSavedUsernameState() 호출은 무시하게 함.
    return () => {
      isMounted = false;
    };
  }, []);

  // 저장소에 아이디 저장
  const persistUsername = useCallback(async (username: string) => {
    await setSavedUsername(username);
    setSavedUsernameState(username);
  }, []);

  // 저장소에서 아이디 삭제
  const clearUsername = useCallback(async () => {
    await clearSavedUsername();
    setSavedUsernameState(null);
  }, []);

  return { savedUsername, isLoaded, persistUsername, clearUsername };
}
