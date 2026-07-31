import { Text, View } from 'react-native';

import { styles } from './request-reminder-countdown.styles';

type RequestReminderCountdownProps = {
  label: string;
};

export function RequestReminderCountdown({ label }: RequestReminderCountdownProps) {
  return (
    <View style={styles.outer}>
      <View style={styles.inner}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>대기 시간</Text>
      </View>
    </View>
  );
}
