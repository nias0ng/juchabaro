import { Platform } from 'react-native';

import { getJson, postForm, postJson } from '@/services/http-client';

import type {
  MoveRequestCreateParams,
  MoveRequestCreateResult,
  MoveRequestDetail,
  MoveRequestListResult,
  MoveRequestScope,
  MoveResponseRequest,
  MoveResponseResult,
} from './types';

export function getMoveRequestDetail(requestId: number, accessToken: string): Promise<MoveRequestDetail> {
  return getJson<MoveRequestDetail>(`/api/move-requests/${requestId}`, accessToken);
}

export function getMoveRequests(scope: MoveRequestScope, accessToken: string): Promise<MoveRequestListResult> {
  return getJson<MoveRequestListResult>(`/api/move-requests?scope=${scope}&size=50`, accessToken);
}

export function postMoveRequestResponse(
  requestId: number,
  request: MoveResponseRequest,
  accessToken: string,
): Promise<MoveResponseResult> {
  return postJson<MoveResponseResult>(`/api/move-requests/${requestId}/responses`, request, accessToken);
}

async function appendImage(formData: FormData, uri: string, index: number): Promise<void> {
  const fileName = `photo-${index}.jpg`;

  if (Platform.OS === 'web') {
    const response = await fetch(uri);
    if (!response.ok) {
      throw new Error('선택한 사진을 불러오지 못했습니다.');
    }

    const blob = await response.blob();
    formData.append('images', blob, fileName);
    return;
  }

  // Android/iOS의 React Native FormData는 로컬 파일을 { uri, name, type } 형태로 받는다.
  formData.append(
    'images',
    { uri, name: fileName, type: 'image/jpeg' } as unknown as Blob,
  );
}

export async function postMoveRequest(
  params: MoveRequestCreateParams,
  accessToken: string,
): Promise<MoveRequestCreateResult> {
  const query = new URLSearchParams({
    targetPlateNumber: params.targetPlateNumber,
    eventType: params.eventType,
    reason: params.reason,
  });
  if (params.zoneName) query.set('zoneName', params.zoneName);

  const formData = new FormData();
  await Promise.all(params.images.map((uri, index) => appendImage(formData, uri, index)));

  return postForm<MoveRequestCreateResult>(`/api/move-requests?${query.toString()}`, formData, accessToken);
}
