import { ApiError } from '@/services/api-error';

import type { LoginRequest, LoginResult, UserProfile } from './types';

const MOCK_RESPONSE_DELAY_MS = 800;
const MOCK_PROFILE_DELAY_MS = 300;
const MOCK_ACCESS_TOKEN = 'mock-access-token';
const MOCK_REFRESH_TOKEN = 'mock-refresh-token';

const mockProfile: UserProfile = {
  userId: 1,
  loginId: 'test',
  phoneNumber: '010-0000-0000',
  buildingNumber: '101',
  unitNumber: '1001',
  nickname: '테스트 사용자',
  role: 'RESIDENT',
  status: 'ACTIVE',
  createdAt: '2026-01-01T00:00:00Z',
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function loginMock(request: LoginRequest): Promise<LoginResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  const loginId = request.loginId.trim().toLowerCase();

  if (loginId === 'server-error') {
    throw new ApiError('서버에 일시적인 문제가 발생했습니다.', 500);
  }

  if (loginId === 'network-error') {
    throw new Error('Mock network error');
  }

  if (loginId === 'fail' || request.password === 'wrong') {
    throw new ApiError('아이디 또는 비밀번호가 올바르지 않습니다.', 401, 1001);
  }

  return {
    accessToken: MOCK_ACCESS_TOKEN,
    refreshToken: MOCK_REFRESH_TOKEN,
    tokenType: 'Bearer',
    expiresIn: 3600,
    userId: mockProfile.userId,
    nickname: mockProfile.nickname,
    role: mockProfile.role,
  };
}

export async function getMyProfileMock(accessToken: string): Promise<UserProfile> {
  await delay(MOCK_PROFILE_DELAY_MS);

  if (accessToken !== MOCK_ACCESS_TOKEN) {
    throw new ApiError('유효하지 않은 목 세션입니다.', 401);
  }

  return mockProfile;
}
