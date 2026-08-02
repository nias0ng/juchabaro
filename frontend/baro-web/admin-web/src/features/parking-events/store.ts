import { defineStore } from 'pinia';
import { ref } from 'vue';

import { useAuthStore } from '@/stores/auth-store';

import { EVENT_ROWS, INITIAL_HISTORY, MOCK_TODAY, findEventRow, normalizeEventId } from './data';
import type { HistoryLogEntry, TimelineEntry } from './types';

export const INITIAL_TIMELINE: TimelineEntry[] = [
  { t: '감지됨', d: 'AI가 주차 사건을 감지했습니다.', time: '10:20' },
  { t: '요청 전송', d: '차주에게 이동 요청을 전송했습니다.', time: '10:20' },
  { t: '확인 대기', d: '차주 응답을 기다리고 있습니다.', time: '10:30' },
];

function formatNow(): string {
  const now = new Date();
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

function formatLogTime(): string {
  // 날짜는 실제 시스템 날짜가 아니라 이 데모가 가리키는 '오늘'(MOCK_TODAY)을 써야
  // 이력 관리의 기본 날짜 필터(오늘)에 방금 남긴 로그가 바로 보인다.
  return `${MOCK_TODAY.replaceAll('-', '.')} ${formatNow()}`;
}

// 이력 관리 화면에는 실제 처리자 계정이 없으니, 로그인된 관리자 닉네임을 그대로 쓴다.
function currentHandlerName(): string {
  const authStore = useAuthStore();
  return authStore.user?.nickname ?? '관리자';
}

// 가장 최근 시드 로그(#L-5842) 다음 번호부터 새 로그를 이어 붙인다.
const FIRST_NEW_LOG_SEQ = 5843;

// 사건 목록(ParkingEventListView)의 '사건 상세' 칸과 사건 상세 페이지(ParkingEventDetailView)가
// 같은 사건에 대해 오탐 처리·재알림·진행 이력을 공유해야 해서 Pinia로 끌어올렸다.
// selectedId도 여기 둬서, 목록에서 행을 고르고 상세 페이지에 갔다가 목록으로 돌아와도
// (컴포넌트가 언마운트·재마운트되어도) 마지막으로 선택했던 행이 그대로 유지된다.
export const useParkingEventStore = defineStore('parking-event', () => {
  const selectedId = ref(EVENT_ROWS[0]!.id);
  const oTamIds = ref<Record<string, true>>({});
  const resentIds = ref<Record<string, true>>({});
  // 관리자가 '완료 처리'로 직접 종결한 사건. 사건 상세 화면의 표시 상태를 덮어쓰는 데 쓴다.
  const completedIds = ref<Record<string, true>>({});
  // 관리자가 '관리자 확인'을 남긴 사건. 중복으로 다시 확인 처리를 남기지 못하게 막는 데 쓴다.
  const reviewedIds = ref<Record<string, true>>({});
  const timelines = ref<Record<string, TimelineEntry[]>>({});
  const history = ref<HistoryLogEntry[]>(INITIAL_HISTORY);
  const nextLogSeq = ref(FIRST_NEW_LOG_SEQ);

  function setSelectedId(id: string) {
    selectedId.value = id;
  }

  // 오탐 처리는 토글이다: 이미 오탐으로 표시된 사건에서 다시 누르면 원래 등록되어 있던
  // 유형으로 되돌린다. 되돌리는 쪽은 실수로 누른 걸 취소하는 것뿐이라 이력에 남기지 않는다.
  function markOtam(id: string) {
    const key = normalizeEventId(id);
    if (oTamIds.value[key]) {
      const { [key]: _removed, ...rest } = oTamIds.value;
      oTamIds.value = rest;
      return;
    }
    oTamIds.value = { ...oTamIds.value, [key]: true };
    history.value = [
      {
        logId: `#L-${nextLogSeq.value}`,
        eventId: `#${key}`,
        car: findEventRow(id)?.car ?? '-',
        actionType: '오탐 처리',
        handler: currentHandlerName(),
        time: formatLogTime(),
        memo: '사건 목록에서 오탐으로 처리함',
      },
      ...history.value,
    ];
    nextLogSeq.value += 1;
  }

  // 관리자가 사건 상세에서 직접 사유를 입력해 사건을 완료 처리한다.
  function completeEvent(id: string, memo: string) {
    const key = normalizeEventId(id);
    completedIds.value = { ...completedIds.value, [key]: true };
    history.value = [
      {
        logId: `#L-${nextLogSeq.value}`,
        eventId: `#${key}`,
        car: findEventRow(id)?.car ?? '-',
        actionType: '완료 처리',
        handler: currentHandlerName(),
        time: formatLogTime(),
        memo,
      },
      ...history.value,
    ];
    nextLogSeq.value += 1;
  }

  // 완료 처리는 아니지만 관리자가 사건을 확인했다는 사유를 남긴다(상태는 바뀌지 않는다).
  function acknowledgeEvent(id: string, memo: string) {
    const key = normalizeEventId(id);
    reviewedIds.value = { ...reviewedIds.value, [key]: true };
    history.value = [
      {
        logId: `#L-${nextLogSeq.value}`,
        eventId: `#${key}`,
        car: findEventRow(id)?.car ?? '-',
        actionType: '관리자 확인',
        handler: currentHandlerName(),
        time: formatLogTime(),
        memo,
      },
      ...history.value,
    ];
    nextLogSeq.value += 1;
  }

  function resend(id: string) {
    const key = normalizeEventId(id);
    resentIds.value = { ...resentIds.value, [key]: true };
    timelines.value = {
      ...timelines.value,
      [key]: [
        ...(timelines.value[key] ?? INITIAL_TIMELINE),
        { t: '요청 재전송', d: '차주에게 이동 요청을 다시 전송했습니다.', time: formatNow() },
      ],
    };
    history.value = [
      {
        logId: `#L-${nextLogSeq.value}`,
        eventId: `#${key}`,
        car: findEventRow(id)?.car ?? '-',
        actionType: '재알림 전송',
        handler: currentHandlerName(),
        time: formatLogTime(),
        memo: '이동 요청 재전송',
      },
      ...history.value,
    ];
    nextLogSeq.value += 1;
  }

  return {
    selectedId,
    oTamIds,
    resentIds,
    completedIds,
    reviewedIds,
    timelines,
    history,
    nextLogSeq,
    setSelectedId,
    markOtam,
    resend,
    completeEvent,
    acknowledgeEvent,
  };
});
