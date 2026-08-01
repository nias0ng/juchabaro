import { useState } from 'react';
import { Text, View } from 'react-native';

import {
  AppButton,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  Stack,
  TextField,
} from '@/components/ui';
import { formatPhoneNumber } from '@/features/auth/validation/signup';
import { HouseholdInfoRow } from '@/features/profile/components/profile-edit/household-info-row';
import { useProfileEditForm } from '@/features/profile/hooks/use-profile-edit-form';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

import { styles } from './profile-edit-screen.styles';

export default function ProfileEditScreen() {
  const { user } = useAuth();
  const [showApiNotice, setShowApiNotice] = useState(false);
  const {
    name,
    setName,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    hasPasswordInput,
    currentPasswordValid,
    newPasswordValid,
    confirmPasswordValid,
    canSave,
  } = useProfileEditForm();

  const householdLabel = user?.buildingNumber && user?.unitNumber
    ? `${user.buildingNumber}동 ${user.unitNumber}호`
    : '위치 정보 없음';

  return (
    <GradientScreenBackground>
      <ResponsiveContainer>
        <ScreenHeader title="내 정보 수정" />

        <Stack gap={Spacing.md} style={styles.content}>
          <TextField
            label="이름"
            value={name}
            onChangeText={setName}
            style={styles.activeField}
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

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>비밀번호 변경</Text>
            <Text style={styles.sectionDescription}>
              비밀번호를 변경하지 않으려면 아래 항목은 비워 두세요.
            </Text>
          </View>

          <TextField
            label="현재 비밀번호"
            value={currentPassword}
            onChangeText={setCurrentPassword}
            secureTextEntry
            autoComplete="current-password"
            placeholder="현재 비밀번호를 입력해 주세요"
            error={
              hasPasswordInput && !currentPasswordValid
                ? '비밀번호를 변경하려면 현재 비밀번호가 필요해요'
                : undefined
            }
          />

          <TextField
            label="새 비밀번호"
            value={newPassword}
            onChangeText={setNewPassword}
            secureTextEntry
            autoComplete="password-new"
            placeholder="새 비밀번호를 입력해 주세요"
            helperText="최소 8자 · 영문 · 숫자 · 특수문자를 포함해 주세요"
            error={
              hasPasswordInput && !newPasswordValid
                ? '영문, 숫자, 특수문자를 모두 포함해 8자 이상 입력해 주세요'
                : undefined
            }
          />

          <TextField
            label="새 비밀번호 확인"
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            secureTextEntry
            autoComplete="password-new"
            placeholder="새 비밀번호를 다시 입력해 주세요"
            error={
              confirmPassword.length > 0 && !confirmPasswordValid
                ? '비밀번호가 일치하지 않아요'
                : undefined
            }
          />

          {showApiNotice ? (
            <View style={styles.apiNotice}>
              <Text style={styles.apiNoticeText}>
                화면 입력과 검증만 적용된 상태예요. API 연결 후 실제로 저장됩니다.
              </Text>
            </View>
          ) : null}

          <AppButton
            label="변경 사항 저장"
            variant="neutral"
            size="lg"
            fullWidth
            disabled={!canSave}
            style={styles.saveButton}
            onPress={() => setShowApiNotice(true)}
          />
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
