import { Pressable, Text, View } from 'react-native';

import { styles } from './request-compose-zone-selector.styles';

type RequestComposeZoneSelectorProps = {
  zoneLabel: string | null;
  onPress: () => void;
};

export function RequestComposeZoneSelector({ zoneLabel, onPress }: RequestComposeZoneSelectorProps) {
  return (
    <Pressable accessibilityRole="button" style={styles.row} onPress={onPress}>
      <View style={styles.radioOuter} />
      <Text style={[styles.zoneText, !zoneLabel && styles.zoneTextPlaceholder]}>
        {zoneLabel ?? '구역을 선택해 주세요'}
      </Text>
      <Text style={styles.selectText}>선택</Text>
    </Pressable>
  );
}
