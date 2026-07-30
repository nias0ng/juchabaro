import { Pressable, Text, View } from 'react-native';

import { styles } from './request-compose-situation-selector.styles';

export type RequestSituation = '이중 주차' | '주차선 침범' | '통로 점유' | '충전구역 점유' | '기타';

const SITUATIONS: RequestSituation[] = ['이중 주차', '주차선 침범', '통로 점유', '충전구역 점유', '기타'];

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
