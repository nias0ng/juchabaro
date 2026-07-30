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
  saveLink: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: '#7a6ff0',
  },
  waitingContent: {
    flex: 1,
    alignItems: 'center',
    gap: Spacing.base + 2,
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  waitingPill: {
    backgroundColor: Palette.white,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 1,
  },
  waitingPillText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: '#5c4fe0',
  },
  waitingLabel: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: '#5c6070',
  },
  statusButton: {
    width: '100%',
    marginTop: 'auto',
    backgroundColor: Palette.gray975,
    borderRadius: Radius.full,
    paddingVertical: Spacing.base + 3,
    alignItems: 'center',
  },
  statusButtonText: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.white,
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
