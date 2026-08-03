import { Text, View } from 'react-native';

import type { ViolationStatus } from '../mocks/violation-history.mock';

import { styles } from './violation-status-badge.styles';

const STATUS_LABEL: Record<ViolationStatus, string> = {
  UNRESOLVED: '미해결',
  RESOLVED: '해결',
};

const STATUS_STYLE: Record<ViolationStatus, { badge: object; text: object }> = {
  UNRESOLVED: { badge: styles.badgeUnresolved, text: styles.textUnresolved },
  RESOLVED: { badge: styles.badgeResolved, text: styles.textResolved },
};

type ViolationStatusBadgeProps = {
  status: ViolationStatus;
};

/** 위반 이력 행의 상태 배지(미해결/해결). 상태별 색 매핑을 이 컴포넌트 하나로 관리한다. */
export function ViolationStatusBadge({ status }: ViolationStatusBadgeProps) {
  const style = STATUS_STYLE[status];

  return (
    <View style={[styles.badge, style.badge]}>
      <Text style={[styles.text, style.text]}>{STATUS_LABEL[status]}</Text>
    </View>
  );
}
