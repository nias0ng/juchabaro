import { Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-reminder-countdown.styles';

const SIZE = 150;
const STROKE_WIDTH = 10;
const RADIUS = (SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

type RequestReminderCountdownProps = {
  label: string;
  caption: string;
  /** 남은 시간 비율. 1(가득 참) → 0(다 참)으로 줄어들면서 진행 arc가 짧아진다. */
  progress: number;
};

export function RequestReminderCountdown({ label, caption, progress }: RequestReminderCountdownProps) {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();
  const clamped = Math.min(1, Math.max(0, progress));
  const dashoffset = CIRCUMFERENCE * (1 - clamped);

  return (
    <View style={styles.outer}>
      <Svg width={SIZE} height={SIZE} style={styles.svg}>
        <Circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke={t.fill.warning.weak}
          strokeWidth={STROKE_WIDTH}
          fill="none"
        />
        <Circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke={t.text.error}
          strokeWidth={STROKE_WIDTH}
          strokeLinecap="round"
          strokeDasharray={`${CIRCUMFERENCE} ${CIRCUMFERENCE}`}
          strokeDashoffset={dashoffset}
          fill="none"
          transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
        />
      </Svg>

      <View style={styles.inner}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>{caption}</Text>
      </View>
    </View>
  );
}
