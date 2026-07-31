import { Pressable, Text, View } from 'react-native';

import { styles } from './violation-status-tabs.styles';

export type ViolationFilter = 'ALL' | 'UNRESOLVED' | 'RESOLVED';

const TABS: { key: ViolationFilter; label: string }[] = [
  { key: 'ALL', label: '전체' },
  { key: 'UNRESOLVED', label: '미해결' },
  { key: 'RESOLVED', label: '해결' },
];

type ViolationStatusTabsProps = {
  active: ViolationFilter;
  onChange: (filter: ViolationFilter) => void;
};

export function ViolationStatusTabs({ active, onChange }: ViolationStatusTabsProps) {
  return (
    <View style={styles.row}>
      {TABS.map((tab) => {
        const selected = tab.key === active;

        return (
          <Pressable
            key={tab.key}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            style={[styles.pill, selected && styles.pillSelected]}
            onPress={() => onChange(tab.key)}
          >
            <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
