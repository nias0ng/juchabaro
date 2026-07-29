import { getJson, postJson } from '@/services/http-client';

import { getMyProfileMock, loginMock, signupMock } from './auth-api.mock';
import type { LoginRequest, LoginResult, SignupRequest, SignupResult, UserProfile } from './types';

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

// 회원가입 API 호출. 성공해도 토큰은 내려오지 않아 자동 로그인은 하지 않는다.
export function signup(request: SignupRequest): Promise<SignupResult> {
  if (useMockAuth) {
    return signupMock(request);
  }

  return postJson<SignupResult>('/api/auth/signup', request);
}
