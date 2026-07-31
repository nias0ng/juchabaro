import { Pressable, Text, View } from 'react-native';

import { styles } from './requests-tab-selector.styles';

export type RequestsScope = 'SENT' | 'RECEIVED';

type RequestsTabSelectorProps = {
  value: RequestsScope;
  onChange: (scope: RequestsScope) => void;
  sentCount: number;
  receivedCount: number;
};

export function RequestsTabSelector({ value, onChange, sentCount, receivedCount }: RequestsTabSelectorProps) {
  const options: { scope: RequestsScope; label: string }[] = [
    { scope: 'SENT', label: `보낸 요청 ${sentCount}` },
    { scope: 'RECEIVED', label: `받은 요청 ${receivedCount}` },
  ];

  return (
    <View style={styles.row}>
      {options.map((option) => {
        const selected = option.scope === value;

        return (
          <Pressable
            key={option.scope}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            style={[styles.pill, selected && styles.pillSelected]}
            onPress={() => onChange(option.scope)}
          >
            <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
