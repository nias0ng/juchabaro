import { Screen, ScreenHeader, Stack } from '@/components/ui';
import { ChannelSelectCard } from '@/features/profile/components/notification-settings/channel-select-card';
import { NotificationToggleRow } from '@/features/profile/components/notification-settings/notification-toggle-row';
import { QuietHoursCard } from '@/features/profile/components/notification-settings/quiet-hours-card';
import { useNotificationSettings } from '@/features/profile/hooks/use-notification-settings';
import { Spacing } from '@/styles';

import { styles } from './notification-settings-screen.styles';

export default function NotificationSettingsScreen() {
  const { settings, setResponseReminder, setEvOverstay, setOfficeNotice, setChannel } =
    useNotificationSettings();

  return (
    <Screen scroll edges={['top', 'right', 'left']}>
      <ScreenHeader title="알림 설정" style={styles.header} />

      <Stack gap={Spacing.base + 2} style={styles.content}>
        <Stack style={styles.toggleCard}>
          <NotificationToggleRow
            label="이동 요청 수신"
            subtitle="끌 수 없는 필수 알림"
            value={settings.moveRequestReceive}
            onChange={() => {}}
            disabled
          />
          <NotificationToggleRow
            label="요청 응답 · 재알림"
            value={settings.responseReminder}
            onChange={setResponseReminder}
          />
          <NotificationToggleRow
            label="충전구역 시간 알림"
            value={settings.evOverstay}
            onChange={setEvOverstay}
          />
          <NotificationToggleRow
            label="관리사무소 공지"
            value={settings.officeNotice}
            onChange={setOfficeNotice}
            bordered={false}
          />
        </Stack>

        <QuietHoursCard startLabel={settings.quietHoursStart} endLabel={settings.quietHoursEnd} />

        <ChannelSelectCard value={settings.channel} onChange={setChannel} />
      </Stack>
    </Screen>
  );
}
