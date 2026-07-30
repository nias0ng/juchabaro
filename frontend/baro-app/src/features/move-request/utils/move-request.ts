import type {
  MoveEventType,
  MoveRequestDetail,
  MoveRequestType,
} from '@/features/move-request/api/types';

const EVENT_TYPE_LABEL: Record<MoveEventType, string> = {
  BAD_PARKING: '불편 주차',
  DOUBLE_PARKING: '이중 주차',
  DISABLED_ZONE_VIOLATION: '장애인 주차구역 위반',
  EV_OVERSTAY: '전기차 충전구역 장기 점유',
  OUT_OF_ZONE: '구역 외 주차',
};

const REQUEST_TYPE_DISPLAY: Record<
  MoveRequestType,
  { label: string; variant: 'manual' | 'ai' }
> = {
  MANUAL: { label: '수동', variant: 'manual' },
  AUTO: { label: 'AI', variant: 'ai' },
};

const DEFAULT_LOCATION_LABEL = '위치 정보 없음';

export type RequestDetailDisplay = {
  requestSourceLabel: string;
  requestSourceVariant: 'manual' | 'ai';
  reasonQuote: string;
  violationTypeLabel: string;
  plateNumber: string;
  location: string;
  photos: { imageId: number; imageUrl: string }[];
};

// 화면에서 표시할 문자열로 변환
export function toRequestDetailDisplay(detail: MoveRequestDetail): RequestDetailDisplay {
  const requestSource = REQUEST_TYPE_DISPLAY[detail.requestType];

  return {
    requestSourceLabel: requestSource.label,
    requestSourceVariant: requestSource.variant,
    reasonQuote: detail.event.reason ? `"${detail.event.reason}"` : '',
    violationTypeLabel: EVENT_TYPE_LABEL[detail.event.eventType],
    plateNumber: detail.targetVehicle.plateNumber,
    location: detail.event.zoneNumber ?? DEFAULT_LOCATION_LABEL,
    photos: detail.event.images
      .filter((image) => image.imageType === 'PARKING_STATE')
      .map((image) => ({ imageId: image.imageId, imageUrl: image.imageUrl })),
  };
}

export type RequestWaitingDisplay = {
  dueTimeLabel: string;
  respondedTimeLabel: string;
};

// 24시간제 "HH:mm" (예정 시간용)
function formatTime24(iso: string): string {
  const date = new Date(iso);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

// 오전/오후 12시간제 (응답 완료 시각용)
function formatTime12(iso: string): string {
  const date = new Date(iso);
  const hours24 = date.getHours();
  const period = hours24 < 12 ? '오전' : '오후';
  const hours12 = hours24 % 12 || 12;
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${period} ${hours12}:${minutes}`;
}

// 응답 완료(RESPONDED) 이후 화면(E-12)에서 표시할 문자열로 변환
export function toRequestWaitingDisplay(detail: MoveRequestDetail): RequestWaitingDisplay {
  const latestResponse = detail.responses[detail.responses.length - 1];

  return {
    dueTimeLabel: detail.dueAt ? formatTime24(detail.dueAt) : '--:--',
    respondedTimeLabel: latestResponse ? formatTime12(latestResponse.respondedAt) : '--',
  };
}

export type RequestCompletedTimelineStep = {
  label: string;
  detail: string;
  isFinal: boolean;
};

export type RequestCompletedDisplay = {
  endTimeLabel: string;
  timeline: RequestCompletedTimelineStep[];
};

// 이동 완료(COMPLETED) 화면(E-13)에서 표시할 문자열로 변환
export function toRequestCompletedDisplay(detail: MoveRequestDetail): RequestCompletedDisplay {
  const latestResponse = detail.responses[detail.responses.length - 1];
  // history를 시간순으로 쌓아두므로, 가장 마지막 EVENT_RESOLVED 알림 시각을 종료 시각으로 쓴다.
  const resolvedEntry = [...detail.history].reverse().find((item) => item.notificationType === 'EVENT_RESOLVED');

  const timeline: RequestCompletedTimelineStep[] = [
    { label: '요청 접수', detail: formatTime24(detail.requestedAt), isFinal: false },
  ];

  if (latestResponse) {
    timeline.push({ label: '이동 진행', detail: formatTime24(latestResponse.respondedAt), isFinal: false });
  }

  timeline.push({ label: '완료', detail: '정상 처리되었습니다', isFinal: true });

  return {
    endTimeLabel: resolvedEntry ? formatTime24(resolvedEntry.sentAt) : '--:--',
    timeline,
  };
}
