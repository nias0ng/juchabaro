import { Image } from 'expo-image';
import { Pressable, Text, View } from 'react-native';

import { styles } from './checkbox-option.styles';

const checkIcon = require('@/assets/images/auth/checkbox-check.png');

type CheckboxOptionProps = {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
};

export function CheckboxOption({ label, checked, onChange }: CheckboxOptionProps) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      style={styles.container}
      onPress={() => onChange(!checked)}
    >
      <View style={[styles.box, checked && styles.boxChecked]}>
        {checked && <Image source={checkIcon} style={styles.checkIcon} contentFit="contain" />}
      </View>
      <Text style={[styles.label, checked && styles.labelChecked]}>{label}</Text>
    </Pressable>
  );
}
