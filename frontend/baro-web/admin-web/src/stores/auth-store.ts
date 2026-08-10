import { defineStore } from 'pinia';
import { ref } from 'vue';

import { getMyProfile, login as loginRequest } from '@/features/auth/api/auth-api';
import type { UserRole, UserStatus } from '@/features/auth/api/types';
import { ApiError } from '@/services/api-error';
import { clearSession, getSession, saveSession } from '@/services/session-storage';

// loading -> guest/authenticated 순으로 바뀐다.
// 앱을 열면 sessionStorage에서 세션을 읽어 GET /api/users/me로 재검증하는 동안은
// 로그인 여부를 판단할 수 없어 loading으로 둔다.
export type AuthStatus = 'loading' | 'guest' | 'authenticated';

export type AuthUser = {
  userId: number;
  nickname: string;
  role: UserRole;
  status: UserStatus;
  phoneNumber: string;
};

export const useAuthStore = defineStore('auth', () => {
  const status = ref<AuthStatus>('loading');
  const user = ref<AuthUser | null>(null);
  const accessToken = ref<string | null>(null);

  let restoreSessionPromise: Promise<void> | null = null;

  function toAuthUser(profile: {
    userId: number;
    name: string;
    role: UserRole;
    status: UserStatus;
    phoneNumber: string;
  }): AuthUser {
    return {
      userId: profile.userId,
      nickname: profile.name,
      role: profile.role,
      status: profile.status,
      phoneNumber: profile.phoneNumber,
    };
  }

  // 라우터 가드와 main.ts에서 여러 번 불러도 실제 복원은 한 번만 실행되도록 promise를 재사용한다.
  function restoreSession(): Promise<void> {
    if (!restoreSessionPromise) {
      restoreSessionPromise = (async () => {
        const session = getSession();
        if (!session) {
          status.value = 'guest';
          return;
        }

        try {
          const profile = await getMyProfile(session.accessToken);
          accessToken.value = session.accessToken;
          user.value = toAuthUser(profile);
          status.value = 'authenticated';
        } catch {
          // 토큰이 만료/무효거나 사용자를 못 찾으면 반쪽짜리 세션으로 두지 않고 guest로 되돌린다.
          clearSession();
          status.value = 'guest';
        }
      })();
    }
    return restoreSessionPromise;
  }

  async function login(loginId: string, password: string): Promise<void> {
    const result = await loginRequest({ loginId, password });

    // 관리자 웹은 ADMIN 계정만 사용할 수 있다. RESIDENT 토큰으로는 로그인 자체를 막는다.
    if (result.role !== 'ADMIN') {
      throw new ApiError('관리자 계정으로만 로그인할 수 있습니다.', 403);
    }

    saveSession({ accessToken: result.accessToken, refreshToken: result.refreshToken });

    const profile = await getMyProfile(result.accessToken);
    accessToken.value = result.accessToken;
    user.value = toAuthUser(profile);
    status.value = 'authenticated';
  }

  function logout(): void {
    clearSession();
    accessToken.value = null;
    user.value = null;
    status.value = 'guest';
  }

  return { status, user, accessToken, restoreSession, login, logout };
});
