import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.sm,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  congestionPill: {
    alignSelf: 'flex-end',
    // ParkingSpotMap 내부 padding(Spacing.lg)이 card padding(Spacing.md + 1)보다 커서,
    // 그 차이만큼 밀어줘야 아래 지도 그리드의 오른쪽 끝과 맞는다.
    marginRight: Spacing.lg - (Spacing.md + 1),
  },
  congestionText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
  },
  congestionTextLow: {
    color: Palette.emerald500,
  },
  congestionTextMedium: {
    color: Palette.amber500,
  },
  congestionTextHigh: {
    color: Palette.red500,
  },
  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xxl + 2,
    padding: Spacing.md + 1,
    gap: Spacing.base,
    ...Shadows.card,
  },
});
