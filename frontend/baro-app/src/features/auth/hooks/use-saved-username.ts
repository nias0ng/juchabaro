import { useCallback, useEffect, useState } from 'react';

import {
  clearSavedUsername,
  getSavedUsername,
  setSavedUsername,
} from '../services/saved-username-storage';

/** 로그인 화면의 "아이디 저장" 체크박스를 위해, 저장된 아이디를 조회·저장·삭제하는 훅. */
export function useSavedUsername() {
  const [savedUsername, setSavedUsernameState] = useState<string | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    // 조회가 끝나기 전에 화면을 벗어나면 언마운트된 컴포넌트에 setState를 호출하게 되므로 isMounted로 막는다.
    let isMounted = true;
    getSavedUsername().then((value) => {
      if (!isMounted) return;
      setSavedUsernameState(value);
      setIsLoaded(true);
    });

    return () => {
      isMounted = false;
    };
  }, []);

  const persistUsername = useCallback(async (username: string) => {
    await setSavedUsername(username);
    setSavedUsernameState(username);
  }, []);

  const clearUsername = useCallback(async () => {
    await clearSavedUsername();
    setSavedUsernameState(null);
  }, []);

  return { savedUsername, isLoaded, persistUsername, clearUsername };
}
