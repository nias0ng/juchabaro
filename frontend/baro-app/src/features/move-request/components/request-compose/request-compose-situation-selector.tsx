import { SegmentedControl } from '@/components/ui';
import type { MoveEventType } from '@/features/move-request/api/types';

export type RequestSituation = '이중 주차' | '주차선 침범' | '통로 점유' | '충전구역 점유' | '기타';

const SITUATION_OPTIONS: { key: RequestSituation; label: string }[] = [
  { key: '이중 주차', label: '이중 주차' },
  { key: '주차선 침범', label: '주차선 침범' },
  { key: '통로 점유', label: '통로 점유' },
  { key: '충전구역 점유', label: '충전구역 점유' },
  { key: '기타', label: '기타' },
];

// POST /move-requests의 eventType 값으로 변환할 때 쓴다.
export const SITUATION_EVENT_TYPE: Record<RequestSituation, MoveEventType> = {
  '이중 주차': 'DOUBLE_PARKING',
  '주차선 침범': 'BAD_PARKING',
  '통로 점유': 'OUT_OF_ZONE',
  '충전구역 점유': 'EV_OVERSTAY',
  기타: 'ETC',
};

type RequestComposeSituationSelectorProps = {
  value: RequestSituation;
  onChange: (situation: RequestSituation) => void;
};

export function RequestComposeSituationSelector({ value, onChange }: RequestComposeSituationSelectorProps) {
  return <SegmentedControl options={SITUATION_OPTIONS} value={value} onChange={onChange} wrap />;
}
