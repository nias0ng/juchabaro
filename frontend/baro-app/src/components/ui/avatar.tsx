import { LinearGradient, type LinearGradientProps } from 'expo-linear-gradient';
import { Text, type StyleProp, type ViewStyle } from 'react-native';

import { FontSize, Gradients } from '@/styles';

import { styles } from './avatar.styles';

const BASE_SIZE = 28;
const BASE_FONT_SIZE = FontSize.sm;

type AvatarProps = {
  /** TODO : 지금은 이름 첫 글자 사용, 나중에 사진 추가 하면 image 추가 하면 됨. */
  label: string;
  size?: number;
  colors?: LinearGradientProps['colors'];
  style?: StyleProp<ViewStyle>;
};

export function Avatar({
  label,
  size = BASE_SIZE,
  colors = Gradients.avatar,
  style,
}: AvatarProps) {
  const fontSize = Math.round((BASE_FONT_SIZE / BASE_SIZE) * size);

  return (
    <LinearGradient
      colors={colors}
      style={[
        styles.circle,
        { width: size, height: size },
        style,
      ]}
    >
      <Text style={[styles.label, { fontSize }]}>{label}</Text>
    </LinearGradient>
  );
}
