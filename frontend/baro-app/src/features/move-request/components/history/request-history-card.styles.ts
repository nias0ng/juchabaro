import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    gap: Spacing.xs + 2,
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    padding: Spacing.md + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  plateNumber: {
    fontSize: 14.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  statusBadge: {
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xs,
  },
  statusText: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
  },
  eventType: {
    fontSize: 12.5,
    color: Palette.gray500,
  },
  message: {
    fontSize: 12.5,
    lineHeight: 19,
    color: Palette.gray500,
  },
  requestedAt: {
    fontSize: 11,
    color: Palette.gray400,
  },
});
