import { Image } from 'react-native';

import { ApiError } from '@/services/api-error';

import type { MoveRequestDetail, MoveResponseRequest, MoveResponseResult } from './types';

const MOCK_RESPONSE_DELAY_MS = 500;

// 네이티브에서 require()는 asset 번호를 돌려주고 resolveAssetSource로 uri를 뽑아야 하는데,
// 웹(react-native-web)은 resolveAssetSource 자체가 없고 require()가 { uri, width, height } 객체를 바로 준다.
function resolveMockImageUri(source: number | string | { uri: string }): string {
  if (typeof source === 'string') return source;
  if (typeof source === 'object' && source !== null && 'uri' in source) return source.uri;
  return Image.resolveAssetSource(source).uri;
}

// 실제 주차 사건 사진 대신 넣어둔 테스트용 로컬 이미지. imageUrl 타입(string)을 맞추려고 uri만 뽑아둔다.
const mockPhoto1 = resolveMockImageUri(require('@/assets/images/resident/request-detail/mock-parking-photo-1.png'));
const mockPhoto2 = resolveMockImageUri(require('@/assets/images/resident/request-detail/mock-parking-photo-2.png'));

// Figma E-11 기준. 아직 응답 전(SENT) 상태라 dueAt/responses가 비어있다.
// let인 이유: POST 응답 mock이 이 값을 실제로 바꿔서, 응답 제출 후 재조회하면 바뀐 상태를 볼 수 있게 한다.
let mockRequestDetail: MoveRequestDetail = {
  requestId: 201,
  requestType: 'AUTO',
  requestStatus: 'SENT',
  requestedAt: new Date().toISOString(),
  dueAt: null,
  requester: null,
  targetVehicle: {
    vehicleId: 10,
    plateNumber: '12가3456',
  },
  event: {
    eventId: 101,
    eventType: 'DOUBLE_PARKING', // BAD_PARKING, DISABLED_ZONE_VIOLATION, EV_OVERSTAY, OUT_OF_ZONE, DOUBLE_PARKING
    reason: '출차 통로를 막고 있어 차량 이동을 요청했습니다.',
    zoneNumber: 'B-14',
    images: [
      { imageId: 401, imageType: 'PARKING_STATE', imageUrl: mockPhoto1 },
      { imageId: 402, imageType: 'PARKING_STATE', imageUrl: mockPhoto2 },
    ],
  },
  responses: [],
  history: [{ notificationType: 'MOVE_REQUEST', sentAt: new Date().toISOString() }],
};

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getMoveRequestDetailMock(requestId: number): Promise<MoveRequestDetail> {
  await delay(MOCK_RESPONSE_DELAY_MS);
  return { ...mockRequestDetail, requestId };
}

export async function postMoveRequestResponseMock(
  requestId: number,
  request: MoveResponseRequest,
): Promise<MoveResponseResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  // 에러 배너 테스트용: /resident/request-detail?requestId=999 로 들어가서 아무 버튼이나 누르면 항상 실패한다.
  if (requestId === 999) {
    throw new ApiError('서버에 일시적인 문제가 발생했습니다.', 500);
  }

  const respondedAt = new Date();
  // CANNOT_MOVE_NOW(이동 어려움)면 명세대로 관리자 확인으로 넘어가고, WILL_MOVE면 응답 완료 상태로 바뀐다.
  const requestStatus = request.responseType === 'CANNOT_MOVE_NOW' ? 'NEED_ADMIN' : 'RESPONDED';
  const dueAt =
    request.responseType === 'WILL_MOVE' && request.estimatedMinutes
      ? new Date(respondedAt.getTime() + request.estimatedMinutes * 60_000).toISOString()
      : null;

  const result: MoveResponseResult = {
    responseId: Date.now(),
    requestId,
    responseType: request.responseType,
    estimatedMinutes: request.estimatedMinutes,
    requestStatus,
    dueAt,
    respondedAt: respondedAt.toISOString(),
  };

  mockRequestDetail = {
    ...mockRequestDetail,
    requestStatus,
    dueAt,
    responses: [
      ...mockRequestDetail.responses,
      {
        responseId: result.responseId,
        responseType: result.responseType,
        estimatedMinutes: result.estimatedMinutes,
        respondedAt: result.respondedAt,
      },
    ],
  };

  return result;
}
