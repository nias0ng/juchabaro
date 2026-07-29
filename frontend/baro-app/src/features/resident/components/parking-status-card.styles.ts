import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

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
    alignSelf: 'flex-start',
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
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },

  legendRow: {
    flexDirection: 'row',
    gap: Spacing.md,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 3,
  },
  legendDotOutline: {
    backgroundColor: Palette.white,
    borderWidth: 1.5,
  },
  legendText: {
    fontSize: 10.5,
    color: Palette.gray500,
  },
});
