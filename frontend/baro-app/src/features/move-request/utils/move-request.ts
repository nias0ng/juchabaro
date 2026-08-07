import type {
  MoveEventType,
  MoveRequestDetail,
  MoveRequestListItem,
  MoveRequestStatus,
  MoveRequestSummary,
  MoveRequestType,
} from '@/features/move-request/api/types';
import type { RequestListItemDisplay } from '@/features/move-request/components/requests-list/request-list-card';
import type { RequestListStatus } from '@/features/move-request/components/requests-list/request-status-badge';
import { toDisplayZoneNumber } from '@/features/parking/utils/parking-zone';

const EVENT_TYPE_LABEL: Record<MoveEventType, string> = {
  BAD_PARKING: '불편 주차',
  DOUBLE_PARKING: '이중 주차',
  DISABLED_ZONE_VIOLATION: '장애인 주차구역 위반',
  EV_OVERSTAY: '전기차 충전구역 장기 점유',
  OUT_OF_ZONE: '구역 외 주차',
  ETC: '기타',
};

const REQUEST_TYPE_DISPLAY: Record<
  MoveRequestType,
  { label: string; variant: 'manual' | 'ai' }
> = {
  MANUAL: { label: '수동', variant: 'manual' },
  AUTO: { label: 'AI', variant: 'ai' },
};

const DEFAULT_LOCATION_LABEL = '위치 정보 없음';

const REQUEST_STATUS_LABEL: Record<MoveRequestStatus, string> = {
  SENT: '응답 대기',
  RESPONDED: '이동 대기중',
  REMINDER_SENT: '재알림 발송',
  COMPLETED: '이동 완료',
  NEED_ADMIN: '관리사무소 전달',
  CANCELLED: '취소됨',
};

export type RequestDetailDisplay = {
  requestId: number;
  requestSourceLabel: string;
  requestSourceVariant: 'manual' | 'ai';
  reasonQuote: string;
  violationTypeLabel: string;
  plateNumber: string;
  location: string;
  requestedAtLabel: string;
  photos: { imageId: number; imageUrl: string }[];
};

// 화면에서 표시할 문자열로 변환
export function toRequestDetailDisplay(detail: MoveRequestDetail): RequestDetailDisplay {
  const requestSource = REQUEST_TYPE_DISPLAY[detail.requestType];

  return {
    requestId: detail.requestId,
    requestSourceLabel: requestSource.label,
    requestSourceVariant: requestSource.variant,
    reasonQuote: detail.message ? `"${detail.message}"` : '',
    violationTypeLabel: EVENT_TYPE_LABEL[detail.event.eventType],
    plateNumber: detail.targetVehicle.plateNumber,
    location: toDisplayZoneNumber(detail.event.zoneNumber) ?? DEFAULT_LOCATION_LABEL,
    requestedAtLabel: formatDateTimeLabel(detail.requestedAt),
    photos: detail.event.images
      .filter((image) => image.imageType === 'PARKING_STATE' || image.imageType === 'REPORT')
      .map((image) => ({ imageId: image.imageId, imageUrl: image.imageUrl })),
  };
}

export type RequestWaitingDisplay = {
  dueTimeLabel: string;
  respondedTimeLabel: string;
};

// 24시간제 "HH:mm" (예정 시간용)
export function formatTime24(iso: string): string {
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

export type RequestTimelineStep = {
  label: string;
  detail: string;
  dotColor?: string;
  labelColor?: string;
  isFinal?: boolean;
};

const REMINDER_ROUND_LABELS = ['1차 재알림', '2차 재알림', '3차 재알림'] as const;
const ADMIN_ESCALATION_DELAY_MS = 60 * 60 * 1000;

function getReminderHistory(detail: MoveRequestDetail): MoveRequestDetail['history'] {
  return detail.history.filter((item) => item.notificationType === 'REMINDER');
}

/** 마지막 재알림 후 한 시간이 지난 시각이 관리사무소 이관 예정 시각이다. */
export function getAdminEscalationDueAt(detail: MoveRequestDetail): string | null {
  const reminders = getReminderHistory(detail);
  const latestReminder = reminders[reminders.length - 1];
  if (!latestReminder) return null;

  const reminderTime = new Date(latestReminder.sentAt).getTime();
  if (Number.isNaN(reminderTime)) return null;
  return new Date(reminderTime + ADMIN_ESCALATION_DELAY_MS).toISOString();
}

export type RequestCompletedDisplay = {
  endTimeLabel: string;
  durationLabel: string | null;
  timeline: RequestTimelineStep[];
};

// 분 단위 숫자를 "18분" / "1시간 5분" 형태로 변환.
export function formatMinutesLabel(minutes: number): string {
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest > 0 ? `${hours}시간 ${rest}분` : `${hours}시간`;
}

// "18분" / "1시간 5분" 형태로 변환. 음수(데이터 이상)면 표시하지 않는다.
export function formatDurationLabel(startIso: string, endIso: string): string | null {
  const minutes = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 60_000);
  if (minutes < 0) return null;
  return formatMinutesLabel(minutes);
}

export function toRequestCompletedDisplay(detail: MoveRequestDetail): RequestCompletedDisplay {
  const latestResponse = detail.responses[detail.responses.length - 1];
  const resolvedEntry = [...detail.history].reverse().find((item) => item.notificationType === 'EVENT_RESOLVED');

  const timeline: RequestTimelineStep[] = [
    { label: '요청 접수', detail: formatTime24(detail.requestedAt), isFinal: false },
  ];

  if (latestResponse) {
    timeline.push({ label: '이동 진행', detail: formatTime24(latestResponse.respondedAt), isFinal: false });
  }

  const reminders = getReminderHistory(detail);
  reminders.forEach((reminder, index) => {
    const roundLabel = REMINDER_ROUND_LABELS[index] ?? `${index + 1}차 재알림`;
    timeline.push({
      label: `${roundLabel} 전송`,
      detail: formatTime24(reminder.sentAt),
      isFinal: false,
      dotColor: '#e5493d',
      labelColor: '#c8492e',
    });
  });

  const escalationDueAt = getAdminEscalationDueAt(detail);
  if (
    resolvedEntry &&
    escalationDueAt &&
    new Date(resolvedEntry.sentAt).getTime() >= new Date(escalationDueAt).getTime()
  ) {
    timeline.push({
      label: '관리사무소 이관',
      detail: formatTime24(escalationDueAt),
      dotColor: '#d4553a',
      labelColor: '#c8492e',
    });
  }

  timeline.push({ label: '완료', detail: '정상 처리되었습니다', isFinal: true });

  return {
    endTimeLabel: resolvedEntry ? formatTime24(resolvedEntry.sentAt) : '--:--',
    durationLabel: resolvedEntry ? formatDurationLabel(detail.requestedAt, resolvedEntry.sentAt) : null,
    timeline,
  };
}

function buildOverdueLeadingSteps(
  detail: MoveRequestDetail,
  firstStepDetail: string,
): RequestTimelineStep[] {
  const latestResponse = detail.responses[detail.responses.length - 1];
  const steps: RequestTimelineStep[] = [
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
  timeline: RequestTimelineStep[];
};

export function toRequestOverdueDisplay(detail: MoveRequestDetail): RequestOverdueDisplay {
  return { timeline: buildOverdueLeadingSteps(detail, formatTime12(detail.requestedAt)) };
}

export type RequestEscalationDisplay = {
  reminderRoundLabel: string;
  escalationDueAt: string | null;
  timeline: RequestTimelineStep[];
  pendingStep?: { label: string; status: string };
};

export function toRequestEscalationDisplay(detail: MoveRequestDetail): RequestEscalationDisplay {
  const reminders = getReminderHistory(detail);
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

  const escalationDueAt = getAdminEscalationDueAt(detail);
  const isTransferred = detail.requestStatus === 'NEED_ADMIN';
  const latestResponse = detail.responses[detail.responses.length - 1];

  if (isTransferred) {
    if (latestResponse?.responseType === 'CANNOT_MOVE_NOW') {
      timeline.push({
        label: '상대방 응답',
        detail: `${formatTime12(latestResponse.respondedAt)} · 지금 이동 어려움`,
        dotColor: '#ff8f6b',
        labelColor: '#d4553a',
      });
    }

    const transferredAt = escalationDueAt ?? latestResponse?.respondedAt ?? null;
    timeline.push({
      label: '관리사무소 이관',
      detail: transferredAt ? formatTime12(transferredAt) : '이관 완료',
      isFinal: true,
      dotColor: '#d4553a',
      labelColor: '#c8492e',
    });
  }

  const latestRoundLabel =
    reminders.length > 0
      ? REMINDER_ROUND_LABELS[reminders.length - 1] ?? `${reminders.length}차 재알림`
      : '관리사무소 이관';

  return {
    reminderRoundLabel: latestRoundLabel,
    escalationDueAt,
    timeline,
    pendingStep: isTransferred
      ? undefined
      : { label: '관리사무소 이관', status: '예정' },
  };
}

export type RequestSummaryDisplay = {
  requestId: number;
  plateNumber: string;
  eventTypeLabel: string;
  statusLabel: string;
  requestedAtLabel: string;
  message: string | null;
};

// 같은 연/월/일인지만 비교한다(시각은 무시).
function isSameDate(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// "오늘 14:20" / "어제 14:20" 형태. 그보다 오래됐으면 "07/31 14:20"으로 날짜를 같이 보여준다.
function formatDateTimeLabel(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const time = formatTime24(iso);

  if (isSameDate(date, now)) return `오늘 ${time}`;

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDate(date, yesterday)) return `어제 ${time}`;

  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}/${day} ${time}`;
}

export function toRequestSummaryDisplay(summary: MoveRequestSummary): RequestSummaryDisplay {
  return {
    requestId: summary.requestId,
    plateNumber: summary.targetPlateNumber,
    eventTypeLabel: EVENT_TYPE_LABEL[summary.eventType],
    statusLabel: REQUEST_STATUS_LABEL[summary.requestStatus],
    requestedAtLabel: formatDateTimeLabel(summary.requestedAt),
    message: summary.message,
  };
}

// 목록에서도 재알림과 관리사무소 이관을 구분해 요청 진행 상황이 끊기지 않게 보여준다.
const LIST_STATUS: Record<MoveRequestStatus, RequestListStatus> = {
  SENT: 'PENDING',
  RESPONDED: 'RESPONDED',
  REMINDER_SENT: 'REMINDER',
  COMPLETED: 'CLOSED',
  NEED_ADMIN: 'ESCALATED',
  CANCELLED: 'CLOSED',
};

// 목록 카드는 개인정보 보호를 위해 번호판 뒷자리를 가려서 보여준다("12가3456" → "12가 ****").
export function maskPlateNumber(plateNumber: string): string {
  return plateNumber.replace(/\d+$/, ' ****');
}

// 요청 목록(E-04) 화면에서 표시할 문자열로 변환
export function toRequestListItemDisplay(item: MoveRequestListItem): RequestListItemDisplay {
  const display = toRequestSummaryDisplay(item);
  const status = LIST_STATUS[item.requestStatus];
  const displayZone = toDisplayZoneNumber(item.zoneNumber);
  const situationLabel = displayZone
    ? `${display.eventTypeLabel} · ${displayZone}`
    : display.eventTypeLabel;

  // COMPLETED만 "N분 만에 이동 완료"로 보여주고, NEED_ADMIN/CANCELLED는 기존 상태 문구를 그대로 쓴다.
  const durationLabel =
    item.requestStatus === 'COMPLETED' && item.resolvedAt
      ? formatDurationLabel(item.requestedAt, item.resolvedAt)
      : null;
  const closedSummary =
    status === 'CLOSED' ? (durationLabel ? `${durationLabel} 만에 이동 완료` : display.statusLabel) : undefined;

  return {
    requestId: display.requestId,
    status,
    timestampLabel: display.requestedAtLabel,
    plateNumber: maskPlateNumber(display.plateNumber),
    situationLabel,
    closedSummary,
    dueAt: status === 'RESPONDED' ? item.dueAt : undefined,
    estimatedMinutes: status === 'RESPONDED' ? item.estimatedMinutes : undefined,
  };
}
