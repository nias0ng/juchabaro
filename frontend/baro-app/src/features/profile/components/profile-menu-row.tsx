import type { ReactNode } from 'react';
import { Pressable, Text, View } from 'react-native';

import { styles } from './profile-menu-row.styles';

type ProfileMenuRowProps = {
  label: string;
  icon?: ReactNode;
  onPress?: () => void;
  disabled?: boolean;
};

export function ProfileMenuRow({ label, icon, onPress, disabled = false }: ProfileMenuRowProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      style={({ pressed }) => [styles.row, pressed && !disabled && styles.rowPressed]}
      onPress={onPress}
    >
      <View style={styles.leading}>
        {icon}
        <Text style={[styles.label, disabled && styles.labelDisabled]}>{label}</Text>
      </View>
      {disabled ? (
        <Text style={styles.badge}>준비 중</Text>
      ) : (
        <Text style={styles.chevron}>›</Text>
      )}
    </Pressable>
  );
}
