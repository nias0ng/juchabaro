import { Text, View } from 'react-native';

import { styles } from './request-reminder-notice.styles';

type RequestReminderNoticeProps = {
  message: string;
};

export function RequestReminderNotice({ message }: RequestReminderNoticeProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}
