import { Pressable, Text, View } from 'react-native';

import type { NotificationChannel } from '@/features/profile/api/types';

import { styles } from './channel-select-card.styles';

type ChannelSelectCardProps = {
  value: NotificationChannel;
  onChange: (value: NotificationChannel) => void;
};

const OPTIONS: { key: NotificationChannel; label: string }[] = [
  { key: 'PUSH', label: '푸시' },
  { key: 'PUSH_SMS', label: '푸시 + 문자' },
];

export function ChannelSelectCard({ value, onChange }: ChannelSelectCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>알림 방식</Text>
      <View style={styles.row}>
        {OPTIONS.map((option) => {
          const selected = option.key === value;
          return (
            <Pressable
              key={option.key}
              accessibilityRole="button"
              accessibilityState={{ selected }}
              style={[styles.option, selected && styles.optionSelected]}
              onPress={() => onChange(option.key)}
            >
              <Text style={[styles.optionLabel, selected && styles.optionLabelSelected]}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
