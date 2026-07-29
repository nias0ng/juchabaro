import { getJson, postJson } from '@/services/http-client';

import { getMyProfileMock, loginMock } from './auth-api.mock';
import type { LoginRequest, LoginResult, UserProfile } from './types';

// TODO(auth-api): 백엔드 인증 API가 준비되면 이 값을 false로 전환하고 실제 API를 검증한다.
const useMockAuth = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_AUTH === 'true';

// 로그인 API 호출
export function login(request: LoginRequest): Promise<LoginResult> {
  if (useMockAuth) {
    return loginMock(request);
  }

  return postJson<LoginResult>('/api/auth/login', request); // 로그인 API 호출
}

// 로그인 상태를 복원할 때 사용
export function getMyProfile(accessToken: string): Promise<UserProfile> {
  if (useMockAuth) {
    return getMyProfileMock(accessToken);
  }

  return getJson<UserProfile>('/api/users/me', accessToken);
}
