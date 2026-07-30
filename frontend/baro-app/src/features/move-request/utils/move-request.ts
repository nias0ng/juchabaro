import type {
  MoveEventType,
  MoveRequestDetail,
  MoveRequestType,
} from '@/features/move-request/api/types';
import type { RequestOverdueTimelineStep } from '@/features/move-request/components/request-overdue/request-overdue-timeline-card';

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
  // 기본(에메랄드/보라) 조합과 다른 색이 필요할 때만 지정한다. (재알림 이력 표시용)
  dotColor?: string;
  labelColor?: string;
};

const REMINDER_ROUND_LABELS = ['1차 재알림', '2차 재알림', '3차 재알림'] as const;

export type RequestCompletedDisplay = {
  endTimeLabel: string;
  durationLabel: string | null;
  timeline: RequestCompletedTimelineStep[];
};

// 분 단위 숫자를 "18분" / "1시간 5분" 형태로 변환.
export function formatMinutesLabel(minutes: number): string {
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest > 0 ? `${hours}시간 ${rest}분` : `${hours}시간`;
}

// "18분" / "1시간 5분" 형태로 변환. 음수(데이터 이상)면 표시하지 않는다.
function formatDurationLabel(startIso: string, endIso: string): string | null {
  const minutes = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 60_000);
  if (minutes < 0) return null;
  return formatMinutesLabel(minutes);
}

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

  // 약속을 어겨서 재알림이 나갔던 적이 있으면, 완료 화면에서도 그 이력을 그대로 보여준다.
  detail.history
    .filter((item) => item.notificationType === 'REMINDER')
    .forEach((reminder, index) => {
      const roundLabel = REMINDER_ROUND_LABELS[index] ?? `${index + 1}차 재알림`;
      timeline.push({
        label: `${roundLabel} 전송`,
        detail: formatTime24(reminder.sentAt),
        isFinal: false,
        dotColor: '#e5493d',
        labelColor: '#c8492e',
      });
    });

  timeline.push({ label: '완료', detail: '정상 처리되었습니다', isFinal: true });

  return {
    endTimeLabel: resolvedEntry ? formatTime24(resolvedEntry.sentAt) : '--:--',
    durationLabel: resolvedEntry ? formatDurationLabel(detail.requestedAt, resolvedEntry.sentAt) : null,
    timeline,
  };
}

// E-14/E-15의 "진행 기록" 앞부분(요청 전송 → 이동 예정 시간 → 미이동 확인)은 두 화면이 동일하게 쓴다.
function buildOverdueLeadingSteps(
  detail: MoveRequestDetail,
  firstStepDetail: string,
): RequestOverdueTimelineStep[] {
  const latestResponse = detail.responses[detail.responses.length - 1];
  const steps: RequestOverdueTimelineStep[] = [
    { label: '이동 요청 전송', detail: firstStepDetail, dotColor: '#7a6ff0' },
  ];

  if (latestResponse && detail.dueAt) {
    const minutesLabel = latestResponse.estimatedMinutes ? ` · ${latestResponse.estimatedMinutes}분 이내` : '';
    steps.push({ label: '이동 예정 시간', detail: `${formatTime12(detail.dueAt)}${minutesLabel}`, dotColor: '#7a6ff0' });
  }

  if (detail.dueAt) {
    steps.push({
      label: '미이동 확인',
      detail: `${formatTime12(detail.dueAt)} · 재알림 대상`,
      dotColor: '#ff8f6b',
      labelColor: '#d4553a',
    });
  }

  return steps;
}

export type RequestOverdueDisplay = {
  timeline: RequestOverdueTimelineStep[];
};

// RESPONDED 상태인데 dueAt이 지난 경우(E-14). 아직 재알림은 안 나갔고, 곧 나갈 예정인 상태.
export function toRequestOverdueDisplay(detail: MoveRequestDetail): RequestOverdueDisplay {
  return { timeline: buildOverdueLeadingSteps(detail, formatTime12(detail.requestedAt)) };
}

export type RequestReminderDisplay = {
  reminderRoundLabel: string;
  timeline: RequestOverdueTimelineStep[];
  pendingStep: { label: string; status: string };
};

// REMINDER_SENT + 응답 있음(E-15). 약속을 어겨서 재알림까지 나간 상태.
export function toRequestReminderDisplay(detail: MoveRequestDetail): RequestReminderDisplay {
  const reminders = detail.history.filter((item) => item.notificationType === 'REMINDER');
  const timeline = buildOverdueLeadingSteps(
    detail,
    `${formatTime12(detail.requestedAt)} · ${detail.targetVehicle.plateNumber}`,
  );

  reminders.forEach((reminder, index) => {
    const roundLabel = REMINDER_ROUND_LABELS[index] ?? `${index + 1}차 재알림`;
    timeline.push({
      label: `${roundLabel} 전송`,
      detail: formatTime12(reminder.sentAt),
      dotColor: '#e5493d',
      labelColor: '#c8492e',
    });
  });

  const latestRoundLabel = REMINDER_ROUND_LABELS[reminders.length - 1] ?? `${reminders.length}차 재알림`;

  return {
    reminderRoundLabel: latestRoundLabel,
    timeline,
    pendingStep: { label: '이동 확인 대기', status: '진행중' },
  };
}
