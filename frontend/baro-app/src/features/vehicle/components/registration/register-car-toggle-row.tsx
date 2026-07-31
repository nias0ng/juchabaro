import { Text, View } from 'react-native';

import { ToggleSwitch } from '@/components/ui';

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
      <ToggleSwitch value={value} onChange={onChange} />
    </View>
  );
}
