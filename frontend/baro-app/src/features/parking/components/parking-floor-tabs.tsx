import { Pressable, Text, View } from 'react-native';

import type { ParkingFloorKey } from '../mocks/parking-floor-overview.mock';

import { styles } from './parking-floor-tabs.styles';

type ParkingFloorTabsProps = {
  floors: { key: ParkingFloorKey; label: string }[];
  active: ParkingFloorKey;
  onChange: (key: ParkingFloorKey) => void;
};

export function ParkingFloorTabs({ floors, active, onChange }: ParkingFloorTabsProps) {
  return (
    <View style={styles.row}>
      {floors.map((floor) => {
        const selected = floor.key === active;

        return (
          <Pressable
            key={floor.key}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            style={[styles.pill, selected && styles.pillSelected]}
            onPress={() => onChange(floor.key)}
          >
            <Text style={[styles.pillText, selected && styles.pillTextSelected]}>{floor.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
