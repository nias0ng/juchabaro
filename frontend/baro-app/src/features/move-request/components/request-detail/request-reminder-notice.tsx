import { Text, View } from 'react-native';

import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-reminder-notice.styles';

type RequestReminderNoticeProps = {
  message: string;
  tone?: 'warning' | 'danger';
};

export function RequestReminderNotice({ message, tone = 'warning' }: RequestReminderNoticeProps) {
  const styles = useThemedStyles(createStyles);
  const isDanger = tone === 'danger';

  return (
    <View style={[styles.container, isDanger && styles.containerDanger]}>
      <Text style={[styles.text, isDanger && styles.textDanger]}>{message}</Text>
    </View>
  );
}
