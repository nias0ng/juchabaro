import type { MoveEventType } from '@/features/move-request/api/types';

export type ViolationStatus = 'UNRESOLVED' | 'RESOLVED';

// 이동 요청의 eventType과 같은 분류를 그대로 쓴다(위반 종류는 결국 같은 개념이라 따로 안 둔다).
export type MockViolationType = MoveEventType;

export type MockViolationItem = {
  id: string;
  type: MockViolationType;
  title: string;
  meta: string;
  status: ViolationStatus;
  monthLabel: string;
};

export type MockViolationSummary = {
  totalCount: number;
  unresolvedCount: number;
  averageResponseMinutes: number;
};

// TODO: 위반 이력 조회 API 완성 후 실제 서버 응답의 최근 90일 통계로 교체
export const MOCK_VIOLATION_SUMMARY: MockViolationSummary = {
  totalCount: 4,
  unresolvedCount: 1,
  averageResponseMinutes: 6,
};

// TODO: 위반 이력 조회 API 완성 후 mock 데이터를 서버 응답(월별 그룹 포함)으로 교체
export const MOCK_VIOLATION_HISTORY: MockViolationItem[] = [
  {
    id: 'violation-1',
    type: 'BAD_PARKING',
    title: '주차선 침범',
    meta: '7/23 14:59 · 침범 43% · B-14',
    status: 'UNRESOLVED',
    monthLabel: '2026년 7월',
  },
  {
    id: 'violation-2',
    type: 'DOUBLE_PARKING',
    title: '이중 주차',
    meta: '7/18 20:41 · 8분 만에 이동',
    status: 'RESOLVED',
    monthLabel: '2026년 7월',
  },
  {
    id: 'violation-3',
    type: 'EV_OVERSTAY',
    title: '충전구역 초과 점유',
    meta: '7/11 09:20 · 72분 이용',
    status: 'RESOLVED',
    monthLabel: '2026년 7월',
  },
  {
    id: 'violation-4',
    type: 'DISABLED_ZONE_VIOLATION',
    title: '장애인 주차구역 위반',
    meta: '7/9 11:04 · 미인증 차량 · B1-D1',
    status: 'RESOLVED',
    monthLabel: '2026년 7월',
  },
  {
    id: 'violation-5',
    type: 'OUT_OF_ZONE',
    title: '구역 외 주차',
    meta: '6/29 18:02 · A-07',
    status: 'RESOLVED',
    monthLabel: '2026년 6월',
  },
  {
    id: 'violation-6',
    type: 'ECT',
    title: '기타',
    meta: '6/15 09:41 · 관리사무소 접수',
    status: 'RESOLVED',
    monthLabel: '2026년 6월',
  },
];
