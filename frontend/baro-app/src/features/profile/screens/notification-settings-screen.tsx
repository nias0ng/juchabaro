import { useState } from 'react';
import { ActivityIndicator, Text, View } from 'react-native';

import {
  AppButton,
  FormErrorBanner,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  Stack,
} from '@/components/ui';
import { NotificationToggleRow } from '@/features/profile/components/notification-settings/notification-toggle-row';
import { QuietHoursCard } from '@/features/profile/components/notification-settings/quiet-hours-card';
import { QuietHoursTimePickerModal } from '@/features/profile/components/notification-settings/quiet-hours-time-picker-modal';
import { useNotificationSettings } from '@/features/profile/hooks/use-notification-settings';
import { Palette, Spacing } from '@/styles';

import { styles } from './notification-settings-screen.styles';

type EditingField = 'start' | 'end' | null;

export default function NotificationSettingsScreen() {
  const {
    settings,
    isLoading,
    isSaving,
    loadErrorMessage,
    saveErrorMessage,
    reload,
    setResponseReminder,
    setEvOverstay,
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
    <GradientScreenBackground>
      <ResponsiveContainer>
        <ScreenHeader title="알림 설정" />

        <Stack gap={Spacing.base + 2} style={styles.content}>
          {isLoading ? (
            <View style={styles.stateContainer}>
              <ActivityIndicator color={Palette.violet600} />
              <Text style={styles.stateText}>알림 설정을 불러오는 중입니다</Text>
            </View>
          ) : loadErrorMessage ? (
            <Stack gap={Spacing.md}>
              <FormErrorBanner message={loadErrorMessage} />
              <AppButton label="다시 불러오기" variant="muted" size="md" onPress={() => void reload()} />
            </Stack>
          ) : (
            <>
              {saveErrorMessage ? <FormErrorBanner message={saveErrorMessage} /> : null}

              <Stack style={styles.toggleCard}>
                <NotificationToggleRow
                  label="이동 요청 수신"
                  subtitle="끌 수 없는 필수 알림"
                  value={settings.moveRequestReceive}
                  onChange={() => {}}
                  disabled
                />
                <NotificationToggleRow
                  label="재알림 받기"
                  value={settings.responseReminder}
                  onChange={setResponseReminder}
                  disabled={isSaving}
                />
                <NotificationToggleRow
                  label="충전구역 시간 초과 알림"
                  value={settings.evOverstay}
                  onChange={setEvOverstay}
                  disabled={isSaving}
                  bordered={false}
                />
              </Stack>

              <QuietHoursCard
                startLabel={settings.quietHoursStart}
                endLabel={settings.quietHoursEnd}
                disabled={isSaving}
                onPressStart={() => setEditingField('start')}
                onPressEnd={() => setEditingField('end')}
              />

              {isSaving ? <Text style={styles.savingText}>변경사항을 저장하는 중입니다...</Text> : null}
            </>
          )}
        </Stack>

        <QuietHoursTimePickerModal
          visible={editingField !== null}
          title={editingField === 'end' ? '방해 금지 종료 시간' : '방해 금지 시작 시간'}
          value={editingField === 'end' ? settings.quietHoursEnd : settings.quietHoursStart}
          onConfirm={handleConfirmTime}
          onClose={() => setEditingField(null)}
        />
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
