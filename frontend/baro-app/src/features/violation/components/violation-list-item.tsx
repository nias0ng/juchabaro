import { Pressable, Text, View } from 'react-native';

import { Palette } from '@/styles';

import type { ViolationHistoryItem } from '../api/types';

import { styles } from './violation-list-item.styles';
import { ViolationStatusBadge } from './violation-status-badge';

const TYPE_ICON_COLOR: Record<ViolationHistoryItem['type'], { outer: string; inner: string }> = {
  BAD_PARKING: { outer: Palette.peach100, inner: Palette.orange400 },
  DOUBLE_PARKING: { outer: Palette.mint100, inner: Palette.emerald500 },
  EV_OVERSTAY: { outer: Palette.mint100, inner: Palette.emerald500 },
  DISABLED_ZONE_VIOLATION: { outer: Palette.sky100, inner: Palette.blue500 },
  OUT_OF_ZONE: { outer: Palette.peach100, inner: Palette.orange400 },
  ETC: { outer: Palette.gray100, inner: Palette.gray500 },
};

type ViolationListItemProps = {
  item: ViolationHistoryItem;
  onPress: () => void;
};

export function ViolationListItem({ item, onPress }: ViolationListItemProps) {
  const iconColor = TYPE_ICON_COLOR[item.type];

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${item.title} 상세 보기`}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
      onPress={onPress}
    >
      <View style={[styles.iconOuter, { backgroundColor: iconColor.outer }]}>
        <View style={[styles.iconInner, { backgroundColor: iconColor.inner }]} />
      </View>

      <View style={styles.content}>
        <Text style={styles.title}>{item.title}</Text>
        <Text style={styles.meta}>{item.meta}</Text>
        <Text style={styles.statusDescription}>{item.statusDescription}</Text>
      </View>

      <ViolationStatusBadge status={item.status} />
    </Pressable>
  );
}
