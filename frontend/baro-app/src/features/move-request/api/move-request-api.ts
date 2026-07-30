import { getJson, postJson } from '@/services/http-client';

import { getMoveRequestDetailMock, postMoveRequestResponseMock } from './move-request-api.mock';
import type { MoveRequestDetail, MoveResponseRequest, MoveResponseResult } from './types';

const useMockMoveRequest = process.env.EXPO_PUBLIC_USE_MOCK_MOVE_REQUEST === 'true';

export function getMoveRequestDetail(requestId: number, accessToken: string): Promise<MoveRequestDetail> {
  if (useMockMoveRequest) {
    return getMoveRequestDetailMock(requestId);
  }

  return getJson<MoveRequestDetail>(`/api/move-requests/${requestId}`, accessToken);
}

export function postMoveRequestResponse(
  requestId: number,
  request: MoveResponseRequest,
  accessToken: string,
): Promise<MoveResponseResult> {
  if (useMockMoveRequest) {
    return postMoveRequestResponseMock(requestId, request);
  }

  return postJson<MoveResponseResult>(`/api/move-requests/${requestId}/responses`, request, accessToken);
}
