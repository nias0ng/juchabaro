import { Text, View } from 'react-native';

import { styles } from './request-overdue-reminder-card.styles';

type RequestOverdueReminderCardProps = {
  countdownLabel: string;
};

export function RequestOverdueReminderCard({ countdownLabel }: RequestOverdueReminderCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>재알림 전송 대기중</Text>
      <Text style={styles.countdown}>{countdownLabel}</Text>
    </View>
  );
}
