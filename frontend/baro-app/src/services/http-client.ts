/** 모든 API 호출이 거치는 공통 HTTP 클라이언트. 백엔드 공통 응답 포맷을 해석해 성공 시 result만, 실패 시 ApiError를 던진다. */
import { ApiError } from './api-error';
import { handleUnauthorized } from './unauthorized-handler';

type ApiEnvelope<T> = {
  httpStatus: string;
  isSuccess: boolean;
  message: string;
  code: number;
  result: T;
};

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL;
const API_LOGS_ENABLED = __DEV__ || process.env.EXPO_PUBLIC_ENABLE_API_LOGS === 'true';

function getSafePath(path: string): string {
  return path.split('?')[0];
}

function getErrorDescription(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}

async function request<T>(path: string, init: RequestInit, requiresAuth = false): Promise<T> {
  if (!BASE_URL) {
    throw new ApiError(
      'API 서버 주소가 설정되지 않았습니다. EXPO_PUBLIC_API_BASE_URL 환경 변수를 확인해 주세요.',
      0,
    );
  }

  const isFormData = init.body instanceof FormData;
  const method = init.method ?? 'GET';
  const safePath = getSafePath(path);
  const startedAt = Date.now();

  if (API_LOGS_ENABLED) {
    console.info(`[API] --> ${method} ${safePath}`);
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...init.headers,
      },
    });
  } catch (error) {
    if (API_LOGS_ENABLED) {
      console.error(`[API] NETWORK_ERROR ${method} ${safePath} - ${getErrorDescription(error)}`);
    }
    throw new ApiError('서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.', 0);
  }

  if (API_LOGS_ENABLED) {
    console.info(`[API] <-- ${response.status} ${method} ${safePath} (${Date.now() - startedAt}ms)`);
  }

  let body: ApiEnvelope<T> | undefined;
  try {
    body = await response.json();
  } catch (error) {
    if (API_LOGS_ENABLED) {
      console.error(`[API] INVALID_JSON ${method} ${safePath} - ${getErrorDescription(error)}`);
    }
    // 본문이 없거나 JSON이 아닌 응답(예: 502)은 body 없이 상태 코드만으로 처리한다.
  }

  if (!response.ok || !body?.isSuccess) {
    if (API_LOGS_ENABLED) {
      console.warn(`[API] FAILED ${method} ${safePath} status=${response.status} code=${body?.code ?? 'none'}`);
    }

    // 로그인/회원가입 실패의 401은 폼 오류로 남겨 두고, 인증 토큰을 넣은 요청만 세션 만료로 처리한다.
    if (requiresAuth && response.status === 401) {
      await handleUnauthorized();
    }

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
  }, Boolean(accessToken));
}

// 일부 필드만 변경하는 API에 사용한다. 전달하지 않은 필드는 서버에서 기존 값을 유지한다.
export function patchJson<T>(path: string, data: unknown, accessToken: string): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    body: JSON.stringify(data),
    headers: { Authorization: `Bearer ${accessToken}` },
  }, true);
}

// 이미지 등 파일 업로드가 필요한 POST. multipart/form-data로 보낸다.
export function postForm<T>(path: string, data: FormData, accessToken?: string): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: data,
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  }, Boolean(accessToken));
}

// accessToken이 필요한 조회용 GET. Authorization 헤더가 필요한 API(예: 내 정보 조회)에서 쓴다.
export function getJson<T>(path: string, accessToken: string): Promise<T> {
  return request<T>(path, {
    method: 'GET',
    headers: { Authorization: `Bearer ${accessToken}` },
  }, true);
}

// accessToken이 필요한 삭제용 DELETE.
export function deleteJson<T>(path: string, accessToken: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'DELETE',
    body: data === undefined ? undefined : JSON.stringify(data),
    headers: { Authorization: `Bearer ${accessToken}` },
  }, true);
}
