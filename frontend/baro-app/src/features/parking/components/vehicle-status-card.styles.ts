import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    minHeight: 168,
    position: 'relative',
    justifyContent: 'center',
    backgroundColor: Palette.gray25,
    borderRadius: Radius.xxl + 2,
    padding: Spacing.lg,
    gap: Spacing.sm,
    ...Shadows.card,
  },
  cardContained: {
    shadowOpacity: 0,
    shadowRadius: 0,
    elevation: 0,
  },
  emptyCard: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerGroup: {
    gap: Spacing.none,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
    backgroundColor: Palette.blue500,
  },
  statusDotViolation: {
    backgroundColor: Palette.red500,
  },
  statusLabel: {
    fontSize: 12,
    fontWeight: FontWeight.bold,
    color: Palette.blue500,
  },
  statusLabelViolation: {
    color: Palette.red500,
  },
  statusTime: {
    marginLeft: 'auto',
    fontSize: 11.5,
    color: Palette.gray400,
  },
  plateRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: Spacing.sm,
  },
  plateText: {
    fontSize: 27,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.4,
  },
  modelText: {
    fontSize: 12.5,
    color: Palette.gray500,
    paddingBottom: 4,
  },
  fieldLabel: {
    fontSize: 11,
    color: Palette.gray400,
  },
  fieldValue: {
    fontSize: 14,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
  fieldValueWarning: {
    color: Palette.red500,
  },
  emptyText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
  detailsRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: Spacing.base,
  },
  detailColumn: {
    flex: 1,
    gap: Spacing.xxs,
  },
  pageIndicatorText: {
    flexShrink: 0,
    marginLeft: 'auto',
    paddingBottom: 1,
    fontSize: 12.5,
    fontWeight: FontWeight.semibold,
    color: Palette.violet500,
  },
});
