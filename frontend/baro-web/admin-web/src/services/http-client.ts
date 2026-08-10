import { ApiError } from './api-error';

type ApiEnvelope<T> = {
  httpStatus: string;
  isSuccess: boolean;
  message: string;
  code: number;
  result: T;
};

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

async function request<T>(path: string, init: RequestInit): Promise<T> {
  if (!BASE_URL) {
    throw new ApiError('API 서버 주소가 설정되지 않았습니다. .env.local의 VITE_API_BASE_URL을 확인하세요.', 0);
  }

  const isFormData = init.body instanceof FormData;

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...init.headers,
    },
  });

  let body: ApiEnvelope<T> | undefined;
  try {
    body = await response.json();
  } catch {
    // 본문이 없거나 JSON이 아닌 응답(예: 204)
  }

  if (!response.ok || !body?.isSuccess) {
    throw new ApiError(body?.message ?? '요청을 처리하지 못했습니다.', response.status, body?.code);
  }

  return body.result;
}

function authHeader(accessToken?: string): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function postJson<T>(path: string, data?: unknown, accessToken?: string): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: authHeader(accessToken),
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}

export function postForm<T>(path: string, data: FormData, accessToken?: string): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: authHeader(accessToken),
    body: data,
  });
}

export function patchJson<T>(path: string, data: unknown, accessToken?: string): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    headers: authHeader(accessToken),
    body: JSON.stringify(data),
  });
}

export function getJson<T>(path: string, accessToken: string): Promise<T> {
  return request<T>(path, {
    method: 'GET',
    headers: authHeader(accessToken),
  });
}

export function deleteJson<T>(path: string, accessToken: string): Promise<T> {
  return request<T>(path, {
    method: 'DELETE',
    headers: authHeader(accessToken),
  });
}
