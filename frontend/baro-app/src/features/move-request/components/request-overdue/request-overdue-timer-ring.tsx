import { useEffect, useRef } from 'react';
import { Animated, Easing, Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { useColorTokens } from '@/hooks/use-color-tokens';
import { useThemedStyles } from '@/hooks/use-themed-styles';

import { createStyles } from './request-overdue-timer-ring.styles';

const SIZE = 150;
const STROKE_WIDTH = 8;
const RADIUS = (SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// 정해진 목표 시각이 없어서(계속 늘어나기만 하는 경과 시간) 진행률 대신 거의 꽉 찬 원을 빠르게 계속 회전시킨다.
const ARC_FRACTION = 0.85;

type RequestOverdueTimerRingProps = {
  label: string;
};

export function RequestOverdueTimerRing({ label }: RequestOverdueTimerRingProps) {
  const styles = useThemedStyles(createStyles);
  const t = useColorTokens();
  const spin = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(spin, {
        toValue: 1,
        duration: 700,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [spin]);

  const rotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });

  return (
    <View style={styles.wrapper}>
      <Animated.View style={[styles.spinner, { transform: [{ rotate }] }]}>
        <Svg width={SIZE} height={SIZE}>
          <Circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} stroke={t.fill.error.weak} strokeWidth={STROKE_WIDTH} fill="none" />
          <Circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            stroke={t.text.error}
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            strokeDasharray={`${CIRCUMFERENCE * ARC_FRACTION} ${CIRCUMFERENCE}`}
            fill="none"
          />
        </Svg>
      </Animated.View>

      <View style={styles.dial}>
        <Text style={styles.time}>{label}</Text>
        <Text style={styles.caption}>경과 시간</Text>
      </View>
    </View>
  );
}
