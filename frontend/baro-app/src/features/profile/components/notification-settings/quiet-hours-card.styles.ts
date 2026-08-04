import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    gap: Spacing.md,
    backgroundColor: Palette.white,
    borderRadius: 26,
    padding: Spacing.md + 4,
    ...Shadows.card,
  },
  title: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  timeRow: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
  },
  timeBox: {
    flex: 1,
    gap: 3,
    backgroundColor: '#f5f4fb',
    borderRadius: Radius.lg + 2,
    padding: Spacing.base + 2,
  },
  timeBoxPressed: {
    backgroundColor: '#ecebf7',
  },
  timeBoxDisabled: {
    opacity: 0.6,
  },
  timeLabel: {
    fontSize: 11,
    color: Palette.gray400,
  },
  timeValue: {
    fontSize: 18,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
});
