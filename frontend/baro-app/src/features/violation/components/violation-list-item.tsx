import { Text, View } from 'react-native';

import { Palette } from '@/styles';

import type { MockViolationItem, MockViolationType } from '../mocks/violation-history.mock';

import { styles } from './violation-list-item.styles';
import { ViolationStatusBadge } from './violation-status-badge';

const TYPE_ICON_COLOR: Record<MockViolationType, string> = {
  BAD_PARKING: Palette.peach100,
  DOUBLE_PARKING: Palette.mint100,
  EV_OVERSTAY: Palette.mint100,
  DISABLED_ZONE_VIOLATION: Palette.sky100,
  OUT_OF_ZONE: Palette.peach100,
  ETC: Palette.gray100,
};

type ViolationListItemProps = {
  item: MockViolationItem;
};

export function ViolationListItem({ item }: ViolationListItemProps) {
  return (
    <View style={styles.row}>
      <View style={[styles.icon, { backgroundColor: TYPE_ICON_COLOR[item.type] }]} />

      <View style={styles.content}>
        <Text style={styles.title}>{item.title}</Text>
        <Text style={styles.meta}>{item.meta}</Text>
      </View>

      <ViolationStatusBadge status={item.status} />
    </View>
  );
}
