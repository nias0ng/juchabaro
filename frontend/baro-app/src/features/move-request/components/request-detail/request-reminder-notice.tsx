import { Text, View } from 'react-native';

import { useTheme } from '@/hooks/use-theme';

import { styles } from './request-reminder-notice.styles';

type RequestReminderNoticeProps = {
  message: string;
  /** 강조해서 먼저 보여줄 한 줄(예: "5분 후 관리자에게 신고 데이터가 자동 전송됩니다."). */
  emphasis?: string;
  /** warning(기본): 재알림/관리사무소 전달 안내. danger: 자동 전송처럼 되돌릴 수 없는 안내. */
  tone?: 'warning' | 'danger';
};

export function RequestReminderNotice({ message, emphasis, tone = 'warning' }: RequestReminderNoticeProps) {
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
      {emphasis ? (
        <Text style={[styles.emphasis, isDanger && { color: theme.danger }]}>{emphasis}</Text>
      ) : null}
      <Text style={[styles.text, isDanger && { color: theme.text }]}>{message}</Text>
    </View>
  );
}
