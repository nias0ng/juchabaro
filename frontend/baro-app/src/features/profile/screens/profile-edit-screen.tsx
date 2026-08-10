import { router } from 'expo-router';
import { Text, View } from 'react-native';

import {
  AppButton,
  FormErrorBanner,
  GradientScreenBackground,
  ResponsiveContainer,
  ScreenHeader,
  Stack,
  TextField,
} from '@/components/ui';
import { formatPhoneNumber } from '@/features/auth/validation/signup';
import { HouseholdInfoRow } from '@/features/profile/components/profile-edit/household-info-row';
import { ProfilePasswordFields } from '@/features/profile/components/profile-edit/profile-password-fields';
import { useProfileUpdateForm } from '@/features/profile/hooks/use-profile-update-form';
import { useAuth } from '@/providers/auth-provider';
import { Spacing } from '@/styles';

import { styles } from './profile-edit-screen.styles';

export default function ProfileEditScreen() {
  const { user } = useAuth();
  const {
    name,
    setName,
    password,
    canSave,
    isSubmitting,
    errorMessage,
    submit,
  } = useProfileUpdateForm();

  const householdLabel = user?.buildingNumber && user?.unitNumber
    ? `${user.buildingNumber}동 ${user.unitNumber}호`
    : '위치 정보 없음';

  return (
    <GradientScreenBackground avoidKeyboard>
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

          <ProfilePasswordFields form={password} />

          {errorMessage ? <FormErrorBanner message={errorMessage} /> : null}

          <AppButton
            label="변경 사항 저장"
            variant="neutral"
            size="lg"
            fullWidth
            loading={isSubmitting}
            disabled={!canSave || isSubmitting}
            style={styles.saveButton}
            onPress={async () => {
              if (await submit()) {
                router.replace('/resident/my-page');
              }
            }}
          />
        </Stack>
      </ResponsiveContainer>
    </GradientScreenBackground>
  );
}
