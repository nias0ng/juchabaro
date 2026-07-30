import type {
  MoveEventType,
  MoveRequestDetail,
  MoveRequestType,
} from '@/features/resident/api/types';

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
