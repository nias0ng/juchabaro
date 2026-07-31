import { useState } from 'react';

import { Screen, ScreenHeader, Stack } from '@/components/ui';
import { ChannelSelectCard } from '@/features/profile/components/notification-settings/channel-select-card';
import { NotificationToggleRow } from '@/features/profile/components/notification-settings/notification-toggle-row';
import { QuietHoursCard } from '@/features/profile/components/notification-settings/quiet-hours-card';
import { QuietHoursTimePickerModal } from '@/features/profile/components/notification-settings/quiet-hours-time-picker-modal';
import { useNotificationSettings } from '@/features/profile/hooks/use-notification-settings';
import { Spacing } from '@/styles';

import { styles } from './notification-settings-screen.styles';

type EditingField = 'start' | 'end' | null;

export default function NotificationSettingsScreen() {
  const {
    settings,
    setResponseReminder,
    setEvOverstay,
    setOfficeNotice,
    setChannel,
    setQuietHoursStart,
    setQuietHoursEnd,
  } = useNotificationSettings();
  const [editingField, setEditingField] = useState<EditingField>(null);

  const handleConfirmTime = (value: string) => {
    if (editingField === 'start') setQuietHoursStart(value);
    if (editingField === 'end') setQuietHoursEnd(value);
    setEditingField(null);
  };

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

        <QuietHoursCard
          startLabel={settings.quietHoursStart}
          endLabel={settings.quietHoursEnd}
          onPressStart={() => setEditingField('start')}
          onPressEnd={() => setEditingField('end')}
        />

        <ChannelSelectCard value={settings.channel} onChange={setChannel} />
      </Stack>

      <QuietHoursTimePickerModal
        visible={editingField !== null}
        title={editingField === 'end' ? '방해 금지 종료 시간' : '방해 금지 시작 시간'}
        value={editingField === 'end' ? settings.quietHoursEnd : settings.quietHoursStart}
        onConfirm={handleConfirmTime}
        onClose={() => setEditingField(null)}
      />
    </Screen>
  );
}
