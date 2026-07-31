import { Pressable, Text, View } from 'react-native';

import type { NotificationTab } from '@/features/notification/hooks/use-notifications';

import { styles } from './notification-tabs.styles';

type NotificationTabsProps = {
  active: NotificationTab;
  onChange: (tab: NotificationTab) => void;
};

const TABS: { key: NotificationTab; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'moveRequest', label: '이동 요청' },
];

export function NotificationTabs({ active, onChange }: NotificationTabsProps) {
  return (
    <View style={styles.row}>
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="button"
            accessibilityState={{ selected: isActive }}
            style={[styles.pill, isActive && styles.pillActive]}
            onPress={() => onChange(tab.key)}
          >
            <Text style={[styles.label, isActive && styles.labelActive]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
