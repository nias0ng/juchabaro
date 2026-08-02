import type { EventRow, HistoryLogEntry } from './types';

// ParkingEventListView(사건 목록)와 ParkingEventDetailView(사건 상세, /events/:eventId)가
// 같은 사건 데이터를 공유한다. id는 목록에서는 '#1032', 라우트 파라미터에서는 '1032' 형태로
// 섞여 쓰이므로 normalizeEventId로 항상 '#' 없는 형태로 맞춰서 비교/저장한다.
export const EVENT_ROWS: EventRow[] = [
  { id: '#1032', car: '12가 3456', type: '미응답', loc: 'B1F 102번 앞', time: '10:30', ai: '92%', st: '진행 중', date: '2026-07-22' },
  { id: '#1031', car: '34나 5678', type: '미이동', loc: 'B1F 120번', time: '10:22', ai: '88%', st: '진행 중', date: '2026-07-22' },
  { id: '#1030', car: '56다 9012', type: '오탐', loc: 'B2F EV-02', time: '10:15', ai: '76%', st: '검토 중', date: '2026-07-22' },
  { id: '#1029', car: '78라 3456', type: '미응답', loc: '주차선 불명', time: '09:58', ai: '91%', st: '진행 중', date: '2026-07-22' },
  { id: '#1028', car: '90마 7890', type: '미이동', loc: 'B1F 102번 옆', time: '09:45', ai: '89%', st: '진행 중', date: '2026-07-22' },
  { id: '#1027', car: '11바 1234', type: '장애인 구역', loc: 'B1F 장애인 03', time: '09:32', ai: '93%', st: '검토 중', date: '2026-07-22' },
  { id: '#1026', car: '22사 5678', type: '전기차 구역', loc: 'B2F EV-01', time: '09:18', ai: '90%', st: '완료', date: '2026-07-22' },
  { id: '#1025', car: '33아 9012', type: '오탐', loc: 'B2F 55번 앞', time: '09:02', ai: '72%', st: '완료', date: '2026-07-22' },

  // 날짜 필터(당일 기준)가 실제로 날짜별 결과를 바꿔 보여주는지 확인할 수 있도록
  // 전날(2026-07-21) 더미 데이터를 넣어둔다. '오늘'을 7/22로 볼 때, 7/21 22시 이전 사건은
  // 모두 이미 해결되어 '완료' 상태다. 22시 이후 사건만 아직 진행/검토 중일 수 있다.
  { id: '#1024', car: '88아 1234', type: '미응답', loc: 'B1F 101번 앞', time: '23:58', ai: '94%', st: '진행 중', date: '2026-07-21' },
  { id: '#1023', car: '12나 5566', type: '미이동', loc: 'B1F 105번', time: '23:40', ai: '87%', st: '진행 중', date: '2026-07-21' },
  { id: '#1022', car: '34다 7788', type: '오탐', loc: 'B2F EV-03', time: '23:12', ai: '71%', st: '검토 중', date: '2026-07-21' },
  { id: '#1021', car: '56라 9900', type: '장애인 구역', loc: 'B1F 장애인 01', time: '22:55', ai: '92%', st: '검토 중', date: '2026-07-21' },
  { id: '#1020', car: '78마 1122', type: '전기차 구역', loc: 'B2F EV-04', time: '22:30', ai: '90%', st: '완료', date: '2026-07-21' },
  { id: '#1019', car: '90바 3344', type: '미응답', loc: 'B1F 110번', time: '22:05', ai: '93%', st: '진행 중', date: '2026-07-21' },
  { id: '#1018', car: '11사 5566', type: '미이동', loc: 'B2F 88번', time: '21:47', ai: '85%', st: '완료', date: '2026-07-21' },
  { id: '#1017', car: '22아 7788', type: '오탐', loc: 'B1F 115번', time: '21:20', ai: '68%', st: '완료', date: '2026-07-21' },
  { id: '#1016', car: '33자 9900', type: '미응답', loc: '주차선 불명', time: '20:58', ai: '91%', st: '완료', date: '2026-07-21' },
  { id: '#1015', car: '44차 1122', type: '장애인 구역', loc: 'B2F 장애인 02', time: '20:33', ai: '95%', st: '완료', date: '2026-07-21' },
  { id: '#1014', car: '55카 3344', type: '미이동', loc: 'B1F 120번', time: '20:10', ai: '88%', st: '완료', date: '2026-07-21' },
  { id: '#1013', car: '66타 5566', type: '전기차 구역', loc: 'B1F EV-05', time: '19:47', ai: '89%', st: '완료', date: '2026-07-21' },
  { id: '#1012', car: '77파 7788', type: '오탐', loc: 'B2F 60번', time: '19:22', ai: '73%', st: '완료', date: '2026-07-21' },
  { id: '#1011', car: '88하 9900', type: '미응답', loc: 'B1F 125번', time: '18:59', ai: '92%', st: '완료', date: '2026-07-21' },
  { id: '#1010', car: '99가 1122', type: '미이동', loc: 'B2F 65번', time: '18:30', ai: '86%', st: '완료', date: '2026-07-21' },
  { id: '#1009', car: '10나 3344', type: '장애인 구역', loc: 'B1F 장애인 03', time: '18:05', ai: '94%', st: '완료', date: '2026-07-21' },
  { id: '#1008', car: '21다 5566', type: '전기차 구역', loc: 'B2F EV-06', time: '17:41', ai: '90%', st: '완료', date: '2026-07-21' },
  { id: '#1007', car: '32라 7788', type: '미응답', loc: 'B1F 130번', time: '17:15', ai: '93%', st: '완료', date: '2026-07-21' },
  { id: '#1006', car: '43마 9900', type: '오탐', loc: '주차선 불명', time: '16:50', ai: '70%', st: '완료', date: '2026-07-21' },
  { id: '#1005', car: '54바 1122', type: '미이동', loc: 'B1F 135번', time: '16:22', ai: '87%', st: '완료', date: '2026-07-21' },
  { id: '#1004', car: '65사 3344', type: '미응답', loc: 'B2F 70번', time: '15:58', ai: '91%', st: '완료', date: '2026-07-21' },
];

export const STATUS_OPTIONS = ['진행 중', '검토 중', '완료'];
export const TYPE_OPTIONS = ['미응답', '미이동', '오탐', '장애인 구역', '전기차 구역'];

export const HISTORY_ACTION_OPTIONS = ['완료 처리', '오탐 처리', '재알림 전송', '관리자 확인'];

// 이력 관리(HistoryView)의 처리 이력 초기 데이터. 사건 목록(EVENT_ROWS)과 같은 사건을
// 가리키므로 차량 번호 등은 EVENT_ROWS와 일치시켜 둔다.
//
// 여기에는 "관리자 손이 실제로 간" 사건만 올라온다. 이 서비스는 AI가 자동으로 감지하고
// 차주에게 연락해 대부분의 사건을 스스로 정리하므로(예: 미응답/미이동이 차주 이동으로
// 완료), 그런 자동 완료 건은 로그에 넣지 않는다. 반면 오탐 처리는 항상 관리자가 직접
// 판단해야 하므로(오탐 여부는 AI가 최종 확정할 수 없음) 오탐으로 끝난 사건은 전부 로그에
// 남긴다.
export const INITIAL_HISTORY: HistoryLogEntry[] = [
  {
    logId: '#L-5842',
    eventId: '#1032',
    car: '12가 3456',
    actionType: '완료 처리',
    handler: '관리자A',
    time: '2026.07.22 10:42',
    memo: '관리자 확인 후 정상 주차로 판단하여 완료 처리',
  },
  {
    logId: '#L-5841',
    eventId: '#1031',
    car: '34나 5678',
    actionType: '오탐 처리',
    handler: '관리자A',
    time: '2026.07.22 10:21',
    memo: '출차 기록 확인, 반복 오탐',
  },
  {
    logId: '#L-5840',
    eventId: '#1030',
    car: '56다 9012',
    actionType: '오탐 처리',
    handler: '관리자A',
    time: '2026.07.22 10:21',
    memo: '차량 등록 정보 일치 확인',
  },
  {
    logId: '#L-5839',
    eventId: '#1031',
    car: '34나 5678',
    actionType: '재알림 전송',
    handler: '관리자B',
    time: '2026.07.22 10:35',
    memo: '허용 시간 30분 연장',
  },
  {
    logId: '#L-5838',
    eventId: '#1029',
    car: '78라 3456',
    actionType: '완료 처리',
    handler: '관리자C',
    time: '2026.07.22 09:58',
    memo: '입차 시간 수정 후 정상 처리',
  },
  {
    logId: '#L-5837',
    eventId: '#1028',
    car: '90마 7890',
    actionType: '관리자 확인',
    handler: '관리자B',
    time: '2026.07.22 09:45',
    memo: '현장 사진 확인 필요',
  },
  {
    logId: '#L-5836',
    eventId: '#1027',
    car: '11바 1234',
    actionType: '구역 수정',
    handler: '관리자A',
    time: '2026.07.22 09:15',
    memo: '구역 경계 오차 보정 (-2.5m)',
  },
  {
    logId: '#L-5835',
    eventId: '#1026',
    car: '22사 5678',
    actionType: '재알림 전송',
    handler: '관리자C',
    time: '2026.07.22 08:47',
    memo: '허용 시간 15분 연장',
  },
  // 2026-07-21 사건 중 오탐으로 종결된 건(관리자 확인이 필요했던 건)만 이력에 남긴다.
  // 같은 날 미응답/미이동/구역 위반이 '완료'로 끝난 나머지는 차주가 자동 안내에 따라
  // 알아서 이동해 AI가 자동으로 종결한 것으로 보고 로그를 남기지 않는다.
  {
    logId: '#L-5834',
    eventId: '#1017',
    car: '22아 7788',
    actionType: '오탐 처리',
    handler: '관리자B',
    time: '2026.07.21 21:20',
    memo: '반복 오탐 패턴으로 판단하여 기각',
  },
  {
    logId: '#L-5833',
    eventId: '#1012',
    car: '77파 7788',
    actionType: '오탐 처리',
    handler: '관리자C',
    time: '2026.07.21 19:22',
    memo: '차량 등록 정보 일치 확인 후 기각',
  },
  {
    logId: '#L-5832',
    eventId: '#1006',
    car: '43마 9900',
    actionType: '오탐 처리',
    handler: '관리자A',
    time: '2026.07.21 16:50',
    memo: '출차 기록 확인, 오탐으로 판단',
  },
];

export function normalizeEventId(id: string): string {
  return id.replace('#', '');
}

export function findEventRow(id: string): EventRow | undefined {
  const key = normalizeEventId(id);
  return EVENT_ROWS.find((r) => normalizeEventId(r.id) === key);
}

export function typeTone(t: string) {
  if (t === '미응답') return 'danger' as const;
  if (t === '미이동' || t === '오탐') return 'info' as const;
  if (t === '장애인 구역') return 'primary' as const;
  return 'success' as const;
}

export function statusTone(st: string) {
  if (st === '진행 중') return 'danger' as const;
  if (st === '검토 중') return 'info' as const;
  return 'success' as const;
}

export function formatDate(value: string): string {
  return value.replaceAll('-', '.');
}
