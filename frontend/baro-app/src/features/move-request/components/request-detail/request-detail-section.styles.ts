import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  mainCard: {
    flexGrow: 1,
    gap: Spacing.base + 1,
    backgroundColor: Palette.gray50,
    paddingTop: Spacing.lg + 4,
    paddingBottom: Spacing.lg,
    paddingHorizontal: Spacing.md + 4,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.07,
    shadowRadius: 10,
    elevation: 4,
  },
  summary: {
    gap: Spacing.xs,
  },
  summaryMeta: {
    fontSize: 11.5,
    color: Palette.gray400,
  },
  summaryTitle: {
    fontSize: 19,
    lineHeight: 24.7,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  summaryReason: {
    fontSize: 12.5,
    lineHeight: 21.25,
    color: Palette.gray500,
  },
  autoEscalation: {
    gap: Spacing.base + 1,
  },
  timerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base + 2,
  },
  label: {
    fontSize: 12,
    color: Palette.gray500,
  },
  timerValue: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.red500,
  },
});
