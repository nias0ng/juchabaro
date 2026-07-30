import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.xs,
  },
  urgentBadge: {
    backgroundColor: Palette.peach100,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 1,
  },
  urgentText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: Palette.orange600,
  },
  mainCard: {
    gap: Spacing.base + 1,
    backgroundColor: Palette.gray50,
    borderTopLeftRadius: Radius.xl + 4,
    borderTopRightRadius: Radius.xl + 4,
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
});
