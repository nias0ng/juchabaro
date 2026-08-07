import { useRef, useState } from 'react';
import { Animated, Pressable, Text, View } from 'react-native';

import { IconGlyph } from '@/components/ui';
import { Palette } from '@/styles';

import { styles } from './quick-action-grid.styles';

export type QuickAction = {
  label: string;
  background: string;
  iconColor: string;
  onPress?: () => void;
};

const CHEVRON_PATH = 'M9 6L15 12L9 18';

type QuickActionGridProps = {
  actions: QuickAction[];
};

export function QuickActionGrid({ actions }: QuickActionGridProps) {
  const scrollX = useRef(new Animated.Value(0)).current;
  const [viewportWidth, setViewportWidth] = useState(0);
  const [contentWidth, setContentWidth] = useState(0);
  const [trackWidth, setTrackWidth] = useState(0);
  const canScroll = contentWidth > viewportWidth;
  const maxScroll = Math.max(contentWidth - viewportWidth, 1);
  const thumbWidth = trackWidth > 0 && contentWidth > 0
    ? Math.max((trackWidth * viewportWidth) / contentWidth, 20)
    : 0;
  const maxThumbOffset = Math.max(trackWidth - thumbWidth, 0);
  const thumbTranslateX = scrollX.interpolate({
    inputRange: [0, maxScroll],
    outputRange: [0, maxThumbOffset],
    extrapolate: 'clamp',
  });

  return (
    <View style={styles.container}>
      <Animated.ScrollView
        horizontal
        directionalLockEnabled
        nestedScrollEnabled
        showsHorizontalScrollIndicator={false}
        snapToAlignment="start"
        snapToInterval={104}
        decelerationRate="fast"
        scrollEventThrottle={16}
        style={styles.scroll}
        contentContainerStyle={styles.row}
        onLayout={(event) => setViewportWidth(event.nativeEvent.layout.width)}
        onContentSizeChange={(width) => setContentWidth(width)}
        onScroll={Animated.event(
          [{ nativeEvent: { contentOffset: { x: scrollX } } }],
          { useNativeDriver: true },
        )}
      >
        {actions.map((action) => (
          <Pressable
            key={action.label}
            accessibilityRole="button"
            accessibilityState={{ disabled: !action.onPress }}
            disabled={!action.onPress}
            style={[styles.action, { backgroundColor: action.background }]}
            onPress={action.onPress}
          >
            <Text style={styles.label}>{action.label}</Text>
            <View style={[styles.chevronBox, { backgroundColor: action.iconColor }]}>
              <IconGlyph
                d={CHEVRON_PATH}
                size={12}
                viewBoxSize={24}
                strokeWidth={2.5}
                color={Palette.white}
              />
            </View>
          </Pressable>
        ))}
      </Animated.ScrollView>

      {canScroll ? (
        <View
          style={styles.progressTrack}
          onLayout={(event) => setTrackWidth(event.nativeEvent.layout.width)}
        >
          <Animated.View
            style={[
              styles.progressThumb,
              { width: thumbWidth, transform: [{ translateX: thumbTranslateX }] },
            ]}
          />
        </View>
      ) : null}
    </View>
  );
}
