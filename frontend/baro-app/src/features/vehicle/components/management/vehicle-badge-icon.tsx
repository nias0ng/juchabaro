import { View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';

import { styles } from './vehicle-badge-icon.styles';

type VehicleBadgeIconName = 'electric' | 'disabled';

// Figma H-02-1/H-02-2 카드의 전기차(zap)/장애인(accessibility) 배지 아이콘 path.
const ZAP_PATH = 'M4.88571 0H8.35714L4.11429 5.6H9L3.21429 12L4.88571 6.66667H0L4.88571 0Z';
const ACCESSIBILITY_BODY_PATH = 'M5.5 5.8L5.2 2.8L8.2 4';
const ACCESSIBILITY_LEG_PATH = 'M5.5 5.8L6.7 7.8H8.5';
const ACCESSIBILITY_RING_PATH =
  'M6.35485 7.41044C6.1449 8.08914 5.71835 8.68035 5.14047 9.0936C4.5626 9.50685 3.86523 9.71936 3.1551 9.69861C2.44498 9.67787 1.7612 9.42501 1.20844 8.97874C0.65567 8.53246 0.264358 7.91736 0.0943877 7.22756C-0.0755824 6.53776 -0.0148468 5.81127 0.2673 5.15927C0.549446 4.50727 1.03746 3.96568 1.65665 3.61738C2.27585 3.26908 2.99211 3.13327 3.69583 3.23072C4.39954 3.32818 5.05194 3.65353 5.55318 4.15699L3.25 6.45L6.35485 7.41044Z';

const ZAP_COLOR = '#f5d800';
const ACCESSIBILITY_COLOR = '#3b82f6';

type VehicleBadgeIconProps = {
  name: VehicleBadgeIconName;
};

/** 전기차/장애인 등록 여부를 나타내는 흰 원형 배지(20x20) 안의 작은 아이콘. */
export function VehicleBadgeIcon({ name }: VehicleBadgeIconProps) {
  return (
    <View style={styles.circle}>
      {name === 'electric' ? (
        <Svg width={10} height={12} viewBox="0 0 9 12" fill="none">
          <Path d={ZAP_PATH} fill={ZAP_COLOR} />
        </Svg>
      ) : (
        <Svg width={10} height={10} viewBox="0 0 10 10" fill="none">
          <Path
            d={ACCESSIBILITY_RING_PATH}
            stroke={ACCESSIBILITY_COLOR}
            strokeWidth={1.2}
            fill="none"
          />
          <Path
            d={ACCESSIBILITY_BODY_PATH}
            stroke={ACCESSIBILITY_COLOR}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <Path
            d={ACCESSIBILITY_LEG_PATH}
            stroke={ACCESSIBILITY_COLOR}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <Circle cx={5.5} cy={1.2} r={1.2} fill={ACCESSIBILITY_COLOR} />
        </Svg>
      )}
    </View>
  );
}
