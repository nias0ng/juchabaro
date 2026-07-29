import { ApiError } from './api-error';

/**
 * 백엔드 공통 응답 포맷
 */
type ApiEnvelope<T> = {
  httpStatus: string;
  isSuccess: boolean;
  message: string;
  code: number;
  result: T;
};

// 실제 배포가 완료되면 -> .env.local을 만들어서 서버 주소 연결
const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL;

// 모든 API 호출이 거치는 공통 통로. 여기 하나만 있으면
// "요청 보내기 → 응답 JSON 파싱 → 성공/실패 판별"을 매번 화면마다 반복하지 않아도 된다.
async function request<T>(path: string, init: RequestInit): Promise<T> {
  if (!BASE_URL) {
    throw new ApiError(
      'API 서버 주소가 설정되지 않았습니다. EXPO_PUBLIC_API_BASE_URL 환경 변수를 확인해 주세요.',
      0,
    );
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  });

  let body: ApiEnvelope<T> | undefined;
  try {
    body = await response.json();
  } catch {
    // 본문이 없거나 JSON이 아닌 응답(예: 502)은 body 없이 상태 코드만으로 처리한다.
  }

  if (!response.ok || !body?.isSuccess) {
    throw new ApiError(body?.message ?? '요청을 처리하지 못했습니다.', response.status, body?.code);
  }

  // 호출 성공
  return body.result;
}

export function postJson<T>(path: string, data: unknown, accessToken?: string): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: JSON.stringify(data),
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  });
}

// accessToken이 필요한 조회용 GET. Authorization 헤더가 필요한 API(예: 내 정보 조회)에서 쓴다.
export function getJson<T>(path: string, accessToken: string): Promise<T> {
  return request<T>(path, {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
