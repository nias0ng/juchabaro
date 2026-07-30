import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { AppButton, Screen, ScreenHeader, Stack, TextField } from '@/components/ui';
import { formatPhoneNumber } from '@/features/auth/validation/signup';
import { HouseholdInfoRow } from '@/features/profile/components/profile-edit/household-info-row';
import { ProfileAvatarEditor } from '@/features/profile/components/profile-edit/profile-avatar-editor';
import { SettingsMenuCard } from '@/features/profile/components/profile-edit/settings-menu-card';
import { useProfileEditForm } from '@/features/profile/hooks/use-profile-edit-form';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

import { styles } from './profile-edit-screen.styles';

export default function ProfileEditScreen() {
  const { user } = useAuth();
  const { isEditing, name, setName, password, setPassword, startEditing, save } = useProfileEditForm();

  const householdLabel = user?.buildingNumber && user?.unitNumber
    ? `${user.buildingNumber}동 ${user.unitNumber}호`
    : '위치 정보 없음';

  return (
    <Screen scroll edges={['top', 'right', 'left']}>
      <ScreenHeader
        title="내 정보 수정"
        style={styles.header}
        right={
          <Pressable accessibilityRole="button" onPress={isEditing ? save : startEditing}>
            <Text style={styles.headerAction}>{isEditing ? '저장' : '수정'}</Text>
          </Pressable>
        }
      />

      <Stack gap={Spacing.md} style={styles.content}>
        <ProfileAvatarEditor name={name} />

        <TextField
          label="이름"
          value={name}
          onChangeText={setName}
          editable={isEditing}
          style={isEditing ? styles.activeField : undefined}
        />

        <TextField
          label="휴대폰 번호"
          value={formatPhoneNumber(user?.phoneNumber ?? '')}
          onChangeText={() => {}}
          editable={false}
          rightAdornment={
            <View style={styles.verifiedBadge}>
              <Text style={styles.verifiedBadgeText}>인증됨</Text>
            </View>
          }
        />

        <HouseholdInfoRow value={householdLabel} />

        {isEditing ? (
          <>
            <TextField
              label="비밀번호"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              placeholder="새 비밀번호 입력"
            />
            {/* 회원 탈퇴 API가 없어 눌러도 동작하지 않는다. */}
            <Pressable accessibilityRole="button" disabled style={styles.withdrawLink}>
              <Text style={styles.withdrawText}>회원 탈퇴</Text>
            </Pressable>
          </>
        ) : (
          <SettingsMenuCard onPressNotificationSettings={() => router.push('/resident/notification-settings')} />
        )}

        {/* TODO(profile-api): PATCH /users/me가 준비되면 실제 저장 요청으로 교체한다. */}
        <AppButton label="변경 사항 저장" variant="neutral" size="lg" fullWidth onPress={save} />
      </Stack>
    </Screen>
  );
}
