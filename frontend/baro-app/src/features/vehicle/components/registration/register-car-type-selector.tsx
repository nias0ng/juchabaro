import { Pressable, Text, View } from 'react-native';

import type { RegisterCarType } from '../../types/register-car';

import { styles } from './register-car-type-selector.styles';

type RegisterCarTypeSelectorProps = {
  value: RegisterCarType;
  onChange: (type: RegisterCarType) => void;
};

const OPTIONS: { type: RegisterCarType; label: string }[] = [
  { type: 'household', label: '세대 차량' },
  { type: 'visitor', label: '방문 차량' },
];

export function RegisterCarTypeSelector({ value, onChange }: RegisterCarTypeSelectorProps) {
  return (
    <View style={styles.row}>
      {OPTIONS.map((option) => {
        const selected = option.type === value;

        return (
          <Pressable
            key={option.type}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            style={[styles.tab, selected && styles.tabSelected]}
            onPress={() => onChange(option.type)}
          >
            <Text style={[styles.tabLabel, selected && styles.tabLabelSelected]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
