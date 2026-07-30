import { LinearGradient } from 'expo-linear-gradient';
import { Text, type StyleProp, type ViewStyle } from 'react-native';

import { Gradients } from '@/styles';

import { styles } from './profile-avatar.styles';

type ProfileAvatarProps = {
  label: string;
  size: number;
  radius: number;
  fontSize: number;
  style?: StyleProp<ViewStyle>;
};

/**
 * 내 정보 화면 전용 아바타. 공통 Avatar는 완전한 원(radius: full)이지만
 * 피그마의 내 정보 화면들은 라운드 사각형(squircle)이라 별도로 둔다.
 */
export function ProfileAvatar({ label, size, radius, fontSize, style }: ProfileAvatarProps) {
  return (
    <LinearGradient
      colors={Gradients.avatar}
      style={[styles.base, { width: size, height: size, borderRadius: radius }, style]}
    >
      <Text style={[styles.label, { fontSize }]}>{label}</Text>
    </LinearGradient>
  );
}
