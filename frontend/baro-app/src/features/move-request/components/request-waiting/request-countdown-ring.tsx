import { Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { Palette } from '@/styles';

import { styles } from './request-countdown-ring.styles';

const SIZE = 170;
const STROKE_WIDTH = 10;
const RADIUS = (SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

type RequestCountdownRingProps = {
  label: string;
  /** 남은 시간 비율. 1(가득 참) → 0(다 참)으로 줄어들면서 진행 arc가 짧아진다. */
  progress: number;
};

export function RequestCountdownRing({ label, progress }: RequestCountdownRingProps) {
  const clamped = Math.min(1, Math.max(0, progress));
  const dashoffset = CIRCUMFERENCE * (1 - clamped);

  return (
    <View style={styles.ring}>
      <Svg width={SIZE} height={SIZE} style={styles.svg}>
        <Circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke={Palette.violet100}
          strokeWidth={STROKE_WIDTH}
          fill="none"
        />
        <Circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke="#5c4fe0"
          strokeWidth={STROKE_WIDTH}
          strokeLinecap="round"
          strokeDasharray={`${CIRCUMFERENCE} ${CIRCUMFERENCE}`}
          strokeDashoffset={dashoffset}
          fill="none"
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
        />
      </Svg>

      <View style={styles.dial}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>REMAINING</Text>
      </View>
    </View>
  );
}
