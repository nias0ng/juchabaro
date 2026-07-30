import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  requestTypeBadge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 1,
  },
  manualRequestBadge: {
    backgroundColor: Palette.sky100,
  },
  aiRequestBadge: {
    backgroundColor: Palette.teal100,
  },
  requestTypeText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
  },
  manualRequestText: {
    color: Palette.blue600,
  },
  aiRequestText: {
    color: Palette.teal600,
  },
  statusContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
    paddingHorizontal: Spacing.lg,
  },
  statusText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
  mainCard: {
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
