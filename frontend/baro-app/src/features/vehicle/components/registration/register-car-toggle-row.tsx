import { Switch, Text, View } from 'react-native';

import { Palette } from '@/styles';

import { styles } from './register-car-toggle-row.styles';

type RegisterCarToggleRowProps = {
  label: string;
  description: string;
  value: boolean;
  onChange: (value: boolean) => void;
};

export function RegisterCarToggleRow({ label, description, value, onChange }: RegisterCarToggleRowProps) {
  return (
    <View style={styles.container}>
      <View style={styles.texts}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.description}>{description}</Text>
      </View>
      <Switch
        value={value}
        onValueChange={onChange}
        trackColor={{ false: Palette.gray200, true: Palette.violet500 }}
        thumbColor={Palette.white}
      />
    </View>
  );
}
