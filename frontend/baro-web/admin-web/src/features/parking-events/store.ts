import { defineStore } from 'pinia';
import { ref } from 'vue';

import { useAuthStore } from '@/stores/auth-store';

import { EVENT_ROWS, INITIAL_HISTORY, findEventRow, normalizeEventId } from './data';
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
  const now = new Date();
  const date = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`;
  return `${date} ${formatNow()}`;
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
  const timelines = ref<Record<string, TimelineEntry[]>>({});
  const history = ref<HistoryLogEntry[]>(INITIAL_HISTORY);
  const nextLogSeq = ref(FIRST_NEW_LOG_SEQ);

  function setSelectedId(id: string) {
    selectedId.value = id;
  }

  function markOtam(id: string) {
    const key = normalizeEventId(id);
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

  return { selectedId, oTamIds, resentIds, timelines, history, nextLogSeq, setSelectedId, markOtam, resend };
});
