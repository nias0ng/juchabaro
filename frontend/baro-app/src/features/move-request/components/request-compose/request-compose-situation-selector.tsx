import { Pressable, Text, View } from 'react-native';

import type { MoveEventType } from '@/features/move-request/api/types';

import { styles } from './request-compose-situation-selector.styles';

export type RequestSituation = '이중 주차' | '주차선 침범' | '통로 점유' | '충전구역 점유' | '기타';

const SITUATIONS: RequestSituation[] = ['이중 주차', '주차선 침범', '통로 점유', '충전구역 점유', '기타'];

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
  return (
    <View style={styles.row}>
      {SITUATIONS.map((situation) => {
        const selected = situation === value;

        return (
          <Pressable
            key={situation}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            style={[styles.pill, selected && styles.pillSelected]}
            onPress={() => onChange(situation)}
          >
            <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{situation}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
