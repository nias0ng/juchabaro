import type { MoveRequestDetail } from './types';

const MOCK_RESPONSE_DELAY_MS = 500;

// Figma E-11 기준. 아직 응답 전(SENT) 상태라 dueAt/responses가 비어있다.
const mockRequestDetail: MoveRequestDetail = {
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
    // 실제 저장소 URL이 아니라, 스와이프 동작 확인용 로딩 가능한 placeholder 이미지.
    images: [
      { imageId: 401, imageType: 'PARKING_STATE', imageUrl: 'https://picsum.photos/seed/parking-event-1/800/600' },
      { imageId: 402, imageType: 'PARKING_STATE', imageUrl: 'https://picsum.photos/seed/parking-event-2/800/600' },
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
