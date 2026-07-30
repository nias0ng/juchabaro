import { getJson } from '@/services/http-client';

import { getMoveRequestDetailMock } from './move-request-api.mock';
import type { MoveRequestDetail } from './types';

// TODO(move-request-api): 백엔드에서 /api/move-requests/{requestId} 확장 명세(event.zoneNumber, history)가 배포되면 이 값을 false로 바꾼다.
const useMockMoveRequest = __DEV__ && process.env.EXPO_PUBLIC_USE_MOCK_MOVE_REQUEST === 'true';

export function getMoveRequestDetail(requestId: number, accessToken: string): Promise<MoveRequestDetail> {
  if (useMockMoveRequest) {
    return getMoveRequestDetailMock(requestId);
  }

  return getJson<MoveRequestDetail>(`/api/move-requests/${requestId}`, accessToken);
}
