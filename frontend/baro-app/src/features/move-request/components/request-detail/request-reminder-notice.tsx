import { Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './request-reminder-notice.styles';

type RequestReminderNoticeProps = {
  message: string;
  tone?: 'warning' | 'danger';
};

export function RequestReminderNotice({ message, tone = 'warning' }: RequestReminderNoticeProps) {
  const theme = useTheme();
  const isDanger = tone === 'danger';

  return (
    <View
      style={[
        styles.container,
        isDanger && {
          borderColor: theme.dangerBorder,
          backgroundColor: theme.dangerSurface,
        },
      ]}
    >
      <Text style={[styles.text, isDanger && { color: theme.text }]}>{message}</Text>
    </View>
  );
}
