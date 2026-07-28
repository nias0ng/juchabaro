import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { getMyProfile, login as loginRequest } from '@/features/auth/api/auth-api';
import type { UserRole } from '@/features/auth/api/types';
import { clearSession, getSession, saveSession } from '@/services/session-storage';

/* 
  AuthProvider :  앱 전반에서 로그인 상태를 관리하는 컴포넌트
*/ 

// 로그인 여부 : loading -> guest/authenticated 순으로 바뀌도록 함. 
// 앱을 키면,SecureStore에서 세션을 읽어오는 동안(비동기)에는 로그인을 한지 안한지 몰라서. 
type AuthStatus = 'loading' | 'guest' | 'authenticated';

// AuthUser의 타입 정의 : 로그인한 사용자 정보 
type AuthUser = {
  userId: number;
  nickname: string;
  role: UserRole;
};

// AuthContextValue의 타입 정의 : 로그인 상태, 사용자 정보, 로그인/로그아웃 함수
type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  login: (loginId: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

// Context는 "이 컴포넌트 트리 어디서든 꺼내 쓸 수 있는 공용 상자"라고 생각하면 된다.
// 로그인 상태를 props로 화면마다 일일이 전달하지 않고, 트리 아무 곳에서나 useAuth()로 꺼낸다.
const AuthContext = createContext<AuthContextValue | null>(null);

// _layout.tsx에서 앱 전체를 이 컴포넌트로 감싸뒀다 (children = 그 안의 모든 화면).
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);

  // 앱이 처음 켜질 때 기기에 저장된 세션이 있는지 확인해서 로그인 상태를 복원
  useEffect(() => {
    getSession().then(async (session) => { 
      if (!session) { // 세션 가져왔는데, 없으면 guest 상태
        setStatus('guest');
        return;
      }

      try {
        // 토큰만 있고 user 정보는 없으니, GET /api/users/me로 다시 조회해서 채움
        const profile = await getMyProfile(session.accessToken);
        setUser({ userId: profile.userId, nickname: profile.nickname, role: profile.role });
        setStatus('authenticated');
      } catch {
        // 토큰이 만료/무효(401)거나 사용자를 못 찾으면(404), 반쪽짜리 세션으로 두지 않고 guest로 되돌린다.
        await clearSession();
        setStatus('guest');
      }
    });
  }, []);

  //화면에서 사용할 longin() 함수 -> 여기서 API 호출/토큰 저장/상태 변경을 처리
  const login = useCallback(async (loginId: string, password: string) => {
    const result = await loginRequest({ loginId, password }); // 로그인 API 호출.
    await saveSession({ accessToken: result.accessToken, refreshToken: result.refreshToken }); // 토큰 저장
    setUser({ userId: result.userId, nickname: result.nickname, role: result.role }); // 사용자 정보 state에 저장
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    await clearSession();
    setUser(null);
    setStatus('guest');
  }, []);

  return (
    <AuthContext.Provider value={{ status, user, login, logout }}>{children}</AuthContext.Provider>
  );
}

// 다른 파일에서는 이 useAuth()만 부르면 status/user/login/logout을 꺼내 쓸 수 있다.
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    // AuthProvider로 감싸지 않은 곳에서 useAuth를 쓰면 실수를 바로 알아챌 수 있게 에러를 던진다.
    throw new Error('useAuth는 AuthProvider 내부에서만 사용할 수 있습니다.');
  }
  return context;
}
