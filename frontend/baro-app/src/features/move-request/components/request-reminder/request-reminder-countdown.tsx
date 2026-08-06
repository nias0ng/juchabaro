import { Text, View } from 'react-native';

import { styles } from './request-reminder-countdown.styles';

type RequestReminderCountdownProps = {
  label: string;
  caption: string;
};

export function RequestReminderCountdown({ label, caption }: RequestReminderCountdownProps) {
  return (
    <View style={styles.outer}>
      <View style={styles.inner}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>{caption}</Text>
      </View>
    </View>
  );
}
