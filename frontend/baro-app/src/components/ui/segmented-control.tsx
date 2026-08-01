import { Pressable, Text, View } from 'react-native';

import { styles } from './segmented-control.styles';

export type SegmentedControlOption<T extends string> = {
  key: T;
  label: string;
};

type SegmentedControlProps<T extends string> = {
  options: SegmentedControlOption<T>[];
  value: T;
  onChange: (value: T) => void;
  wrap?: boolean;
};

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  wrap = false,
}: SegmentedControlProps<T>) {
  return (
    <View style={[styles.row, wrap && styles.rowWrap]}>
      {options.map((option) => {
        const selected = option.key === value;

        return (
          <Pressable
            key={option.key}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            style={[styles.pill, selected && styles.pillSelected]}
            onPress={() => onChange(option.key)}
          >
            <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{option.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
