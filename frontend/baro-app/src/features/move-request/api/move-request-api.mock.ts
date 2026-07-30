import { Image } from 'react-native';

import { ApiError } from '@/services/api-error';

import type {
  MoveRequestDetail,
  MoveRequestListResult,
  MoveRequestScope,
  MoveRequestSummary,
  MoveResponseRequest,
  MoveResponseResult,
} from './types';

const MOCK_RESPONSE_DELAY_MS = 500;
// mock 전용 : 15초 지나면 COMPLETED 상태로 전환.
const MOCK_AUTO_COMPLETE_DELAY_MS = 15_000;

// 네이티브에서 require()는 asset 번호를 돌려주고 resolveAssetSource로 uri를 뽑아야 하는데,
// 웹(react-native-web)은 resolveAssetSource 자체가 없고 require()가 { uri, width, height } 객체를 바로 준다.
function resolveMockImageUri(source: number | string | { uri: string }): string {
  if (typeof source === 'string') return source;
  if (typeof source === 'object' && source !== null && 'uri' in source) return source.uri;
  return Image.resolveAssetSource(source).uri;
}

// 실제 주차 사건 사진 대신 넣어둔 테스트용 로컬 이미지. imageUrl 타입(string)을 맞추려고 uri만 뽑아둔다.
const mockPhoto1 = resolveMockImageUri(require('@/assets/images/move-request/request-detail/mock-parking-photo-1.png'));
const mockPhoto2 = resolveMockImageUri(require('@/assets/images/move-request/request-detail/mock-parking-photo-2.png'));

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

// RESPONDED 상태로 진입한 시각(ms). 이 값 + MOCK_AUTO_COMPLETE_DELAY_MS가 지나면 자동으로 COMPLETED 처리한다.
let mockRespondedAtMs: number | null = null;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// mock 전용: RESPONDED 상태가 일정 시간 유지되면 하드웨어가 이동을 감지해 COMPLETED로 넘어간 것처럼 흉내낸다.
function applyMockAutoComplete(): void {
  if (mockRequestDetail.requestStatus !== 'RESPONDED' || mockRespondedAtMs === null) return;
  if (Date.now() < mockRespondedAtMs + MOCK_AUTO_COMPLETE_DELAY_MS) return;

  const resolvedAt = new Date();
  mockRequestDetail = {
    ...mockRequestDetail,
    requestStatus: 'COMPLETED',
    history: [...mockRequestDetail.history, { notificationType: 'EVENT_RESOLVED', sentAt: resolvedAt.toISOString() }],
  };
  mockRespondedAtMs = null;
}

// E-13(이동 완료) 화면 확인용: /resident/request-detail?requestId=998 로 들어가면 완료 처리된 상태를 바로 볼 수 있다.
function buildCompletedMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 20 * 60_000);
  const respondedAt = new Date(Date.now() - 12 * 60_000);
  const resolvedAt = new Date();

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'COMPLETED',
    requestedAt: requestedAt.toISOString(),
    dueAt: null,
    responses: [
      {
        responseId: 9001,
        responseType: 'WILL_MOVE',
        estimatedMinutes: 10,
        respondedAt: respondedAt.toISOString(),
      },
    ],
    history: [
      { notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() },
      { notificationType: 'EVENT_RESOLVED', sentAt: resolvedAt.toISOString() },
    ],
  };
}

// E-16 확인용: /resident/request-detail?requestId=993 로 들어가면 재알림(1차)까지 나갔다가 완료된 상태.
// 완료 화면 타임라인에 "1차 재알림 전송" 이력이 같이 보여야 한다.
function buildCompletedWithReminderMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 90 * 60_000);
  const respondedAt = new Date(Date.now() - 85 * 60_000);
  const reminderAt = new Date(Date.now() - 40 * 60_000);
  const resolvedAt = new Date();

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'COMPLETED',
    requestedAt: requestedAt.toISOString(),
    dueAt: null,
    responses: [
      {
        responseId: 9002,
        responseType: 'WILL_MOVE',
        estimatedMinutes: 30,
        respondedAt: respondedAt.toISOString(),
      },
    ],
    history: [
      { notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() },
      { notificationType: 'REMINDER', sentAt: reminderAt.toISOString() },
      { notificationType: 'EVENT_RESOLVED', sentAt: resolvedAt.toISOString() },
    ],
  };
}

// E-11 무응답 확인용: /resident/request-detail?requestId=997 로 들어가면 1차 재알림까지 나간 상태(응답 버튼은 그대로 있음).
function buildReminderSentMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 70 * 60_000);
  const reminderAt = new Date(Date.now() - 10 * 60_000);

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'REMINDER_SENT',
    requestedAt: requestedAt.toISOString(),
    dueAt: null,
    responses: [],
    history: [
      { notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() },
      { notificationType: 'REMINDER', sentAt: reminderAt.toISOString() },
    ],
  };
}

// E-14 확인용: /resident/request-detail?requestId=995 로 들어가면 응답은 했지만 dueAt이 지난(아직 재알림 전) 상태.
function buildOverdueMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 40 * 60_000);
  const respondedAt = new Date(Date.now() - 35 * 60_000);
  const dueAt = new Date(Date.now() - 5 * 60_000);

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'RESPONDED',
    requestedAt: requestedAt.toISOString(),
    dueAt: dueAt.toISOString(),
    responses: [
      { responseId: 9101, responseType: 'WILL_MOVE', estimatedMinutes: 30, respondedAt: respondedAt.toISOString() },
    ],
    history: [{ notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() }],
  };
}

// E-15 확인용: /resident/request-detail?requestId=994 로 들어가면 응답 후 약속을 어겨서 1차 재알림까지 나간 상태.
function buildReminderOverdueMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 60 * 60_000);
  const respondedAt = new Date(Date.now() - 55 * 60_000);
  const dueAt = new Date(Date.now() - 25 * 60_000);
  const reminderAt = new Date(Date.now() - 10 * 60_000);

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'REMINDER_SENT',
    requestedAt: requestedAt.toISOString(),
    dueAt: dueAt.toISOString(),
    responses: [
      { responseId: 9102, responseType: 'WILL_MOVE', estimatedMinutes: 30, respondedAt: respondedAt.toISOString() },
    ],
    history: [
      { notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() },
      { notificationType: 'REMINDER', sentAt: reminderAt.toISOString() },
    ],
  };
}

// 관리사무소 전달 확인용: /resident/request-detail?requestId=996 로 들어가면 NEED_ADMIN 상태(응답 버튼 없이 안내만).
function buildNeedAdminMockDetail(requestId: number): MoveRequestDetail {
  const requestedAt = new Date(Date.now() - 130 * 60_000);
  const reminderAt = new Date(Date.now() - 70 * 60_000);

  return {
    ...mockRequestDetail,
    requestId,
    requestStatus: 'NEED_ADMIN',
    requestedAt: requestedAt.toISOString(),
    dueAt: null,
    responses: [],
    history: [
      { notificationType: 'MOVE_REQUEST', sentAt: requestedAt.toISOString() },
      { notificationType: 'REMINDER', sentAt: reminderAt.toISOString() },
    ],
  };
}

export async function getMoveRequestDetailMock(requestId: number): Promise<MoveRequestDetail> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  if (requestId === 998) {
    return buildCompletedMockDetail(requestId);
  }

  if (requestId === 993) {
    return buildCompletedWithReminderMockDetail(requestId);
  }

  if (requestId === 997) {
    return buildReminderSentMockDetail(requestId);
  }

  if (requestId === 996) {
    return buildNeedAdminMockDetail(requestId);
  }

  if (requestId === 995) {
    return buildOverdueMockDetail(requestId);
  }

  if (requestId === 994) {
    return buildReminderOverdueMockDetail(requestId);
  }

  applyMockAutoComplete();

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

  mockRespondedAtMs = requestStatus === 'RESPONDED' ? respondedAt.getTime() : null;

  return result;
}

const mockMoveRequestSummaries: MoveRequestSummary[] = [
  {
    requestId: 201,
    eventId: 101,
    requesterUserId: null,
    targetVehicleId: 10,
    targetPlateNumber: '12가3456',
    requestType: 'AUTO',
    requestStatus: 'SENT',
    eventType: 'DOUBLE_PARKING',
    message: '출차 통로를 막고 있어 차량 이동을 요청했습니다.',
    requestedAt: new Date(Date.now() - 5 * 60_000).toISOString(),
    dueAt: null,
    reminderCount: 0,
  },
  {
    requestId: 998,
    eventId: 108,
    requesterUserId: null,
    targetVehicleId: 10,
    targetPlateNumber: '12가3456',
    requestType: 'AUTO',
    requestStatus: 'COMPLETED',
    eventType: 'BAD_PARKING',
    message: '비상 통로를 막고 있어 이동 요청되었습니다.',
    requestedAt: new Date(Date.now() - 20 * 60 * 60_000).toISOString(),
    dueAt: null,
    reminderCount: 0,
  },
  {
    requestId: 996,
    eventId: 109,
    requesterUserId: null,
    targetVehicleId: 10,
    targetPlateNumber: '12가3456',
    requestType: 'AUTO',
    requestStatus: 'NEED_ADMIN',
    eventType: 'OUT_OF_ZONE',
    message: '지정 구역 외 주차로 이동 요청되었습니다.',
    requestedAt: new Date(Date.now() - 3 * 24 * 60 * 60_000).toISOString(),
    dueAt: null,
    reminderCount: 1,
  },
];

export async function getMoveRequestsMock(scope: MoveRequestScope): Promise<MoveRequestListResult> {
  await delay(MOCK_RESPONSE_DELAY_MS);

  // 이 mock 사용자는 항상 "받는 입장"만 테스트하므로, SENT(내가 보낸 요청)는 비워둔다.
  const moveRequests = scope === 'SENT' ? [] : mockMoveRequestSummaries;

  return {
    moveRequests,
    page: 0,
    size: 20,
    totalElements: moveRequests.length,
    totalPages: 1,
  };
}
