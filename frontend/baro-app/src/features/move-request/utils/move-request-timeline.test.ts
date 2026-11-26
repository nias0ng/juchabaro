import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { MoveRequestDetail } from '../api/types';
import {
  toRequestCompletedDisplay,
  toRequestEscalationDisplay,
  toRequestOverdueDisplay,
  type RequestTimelineStep,
} from './move-request';

function makeDetail(overrides: Record<string, unknown> = {}): MoveRequestDetail {
  return {
    requestStatus: 'REMINDER_SENT',
    requestedAt: '2026-08-01T14:30:00+09:00',
    dueAt: '2026-08-01T14:50:00+09:00',
    resolvedAt: null,
    targetVehicle: { vehicleId: 1, plateNumber: '12가 3456' },
    responses: [
      { responseType: 'WILL_MOVE', respondedAt: '2026-08-01T14:32:00+09:00', estimatedMinutes: 20 },
    ],
    history: [{ notificationType: 'REMINDER', sentAt: '2026-08-01T15:00:00+09:00' }],
    ...overrides,
  } as unknown as MoveRequestDetail;
}

const escalated = makeDetail({ requestStatus: 'NEED_ADMIN' });
const completed = makeDetail({ requestStatus: 'COMPLETED', resolvedAt: '2026-08-01T16:30:00+09:00' });

const allTimelines: RequestTimelineStep[][] = [
  toRequestOverdueDisplay(makeDetail()).timeline,
  toRequestEscalationDisplay(makeDetail()).timeline,
  toRequestEscalationDisplay(escalated).timeline,
  toRequestCompletedDisplay(completed).timeline,
];

function findStep(timeline: RequestTimelineStep[], labelPart: string): RequestTimelineStep {
  const step = timeline.find((item) => item.label.includes(labelPart));
  assert.ok(step, `"${labelPart}" 단계가 있어야 한다`);
  return step;
}

test('타임라인 단계에 색상 값이 들어가지 않는다', () => {
  for (const step of allTimelines.flat()) {
    assert.equal('dotColor' in step, false);
    assert.equal('labelColor' in step, false);
    assert.ok(step.tone === undefined || ['brand', 'warning', 'error'].includes(step.tone));
  }
});

test('보낸 요청과 예정 시간 단계는 brand 톤이다', () => {
  const timeline = toRequestOverdueDisplay(makeDetail()).timeline;
  assert.equal(findStep(timeline, '이동 요청 전송').tone, 'brand');
  assert.equal(findStep(timeline, '이동 예정 시간').tone, 'brand');
});

test('미이동 확인 단계는 warning 톤이다', () => {
  assert.equal(findStep(toRequestOverdueDisplay(makeDetail()).timeline, '미이동 확인').tone, 'warning');
});

test('재알림 전송과 관리사무소 이관 단계는 error 톤이다', () => {
  const timeline = toRequestEscalationDisplay(escalated).timeline;
  assert.equal(findStep(timeline, '재알림 전송').tone, 'error');
  assert.equal(findStep(timeline, '관리사무소 이관').tone, 'error');
});

test('톤이 없는 단계는 tone이 undefined다', () => {
  assert.equal(findStep(toRequestCompletedDisplay(completed).timeline, '요청 접수').tone, undefined);
});
