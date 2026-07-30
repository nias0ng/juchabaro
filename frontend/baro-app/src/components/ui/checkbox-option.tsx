import { Image } from 'expo-image';
import { Pressable, Text, View, type StyleProp, type TextStyle } from 'react-native';

import { styles } from './checkbox-option.styles';

const checkIcon = require('@/assets/images/auth/checkbox-check.png');

type CheckboxOptionProps = {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  labelStyle?: StyleProp<TextStyle>;
};

export function CheckboxOption({ label, checked, onChange, labelStyle }: CheckboxOptionProps) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      style={styles.container}
      hitSlop={{ top: 12, bottom: 12, left: 8, right: 8 }}
      onPress={() => onChange(!checked)}
    >
      <View style={[styles.box, checked && styles.boxChecked]}>
        {checked && <Image source={checkIcon} style={styles.checkIcon} contentFit="contain" />}
      </View>
      <Text style={[styles.label, checked && styles.labelChecked, labelStyle]}>{label}</Text>
    </Pressable>
  );
}
