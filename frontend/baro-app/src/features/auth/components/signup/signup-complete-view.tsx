import { LinearGradient } from 'expo-linear-gradient';
import { Text, View } from 'react-native';

import { AppButton } from '@/components/ui';

import type { SignupAccountFormValues, SignupHouseholdFormValues } from '../../types/signup';

import { styles } from './signup-complete-view.styles';

const COMPLETE_ICON_GRADIENT = ['#8b7ff0', '#6fcfc4'] as const;
const PROFILE_AVATAR_GRADIENT = ['#6fcfc4', '#8b7ff0'] as const;

type SignupCompleteViewProps = {
  account: SignupAccountFormValues;
  household: SignupHouseholdFormValues;
  complexName: string;
  onRegisterVehicle: () => void;
  onGoHome: () => void;
};

export function SignupCompleteView({
  account,
  household,
  complexName,
  onRegisterVehicle,
  onGoHome,
}: SignupCompleteViewProps) {
  const initial = account.name.trim().charAt(0) || '?';

  return (
    <View style={styles.container}>
      <View style={styles.iconCircle}>
        <LinearGradient
          colors={COMPLETE_ICON_GRADIENT}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.iconGradient}
        />
      </View>

      <Text style={styles.heading}>{'반갑습니다!\n주차바로 회원가입 완료'}</Text>
      <Text style={styles.subheading}>
        {'이제 차량을 등록하고 아파트 내 주차\n서비스를 편리하게 이용해보세요.'}
      </Text>

      <View style={styles.profileCard}>
        <LinearGradient
          colors={PROFILE_AVATAR_GRADIENT}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={styles.profileAvatar}
        >
          <Text style={styles.profileAvatarText}>{initial}</Text>
        </LinearGradient>
        <View style={styles.profileInfo}>
          <Text style={styles.profileName}>{account.name}</Text>
          <Text style={styles.profileAddress}>
            {`${complexName} ${household.buildingNumber}동 ${household.unitNumber}호`}
          </Text>
        </View>
        <View style={styles.residentBadge}>
          <Text style={styles.residentBadgeText}>입주민</Text>
        </View>
      </View>

      <View style={styles.actions}>
        <AppButton label="차량 등록하기" variant="neutral" size="lg" fullWidth onPress={onRegisterVehicle} />
        <AppButton label="홈으로 이동" variant="muted" size="lg" fullWidth onPress={onGoHome} />
      </View>
    </View>
  );
}
