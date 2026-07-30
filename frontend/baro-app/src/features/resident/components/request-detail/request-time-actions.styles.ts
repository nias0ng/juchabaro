import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.base + 2,
  },
  heading: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.gray700,
  },
  immediateButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    backgroundColor: Palette.gray975,
    borderRadius: Radius.lg,
    paddingVertical: Spacing.md + 2,
    paddingHorizontal: Spacing.lg,
  },
  immediateButtonText: {
    fontSize: 17,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  immediateButtonArrow: {
    fontSize: 17,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  timedRow: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
  },
  timedButton10: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#eae8fb',
    borderRadius: Radius.lg,
    paddingVertical: Spacing.md,
  },
  timedButton10Text: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.violet600,
  },
  timedButton30: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e1f8f5',
    borderRadius: Radius.lg,
    paddingVertical: Spacing.md,
  },
  timedButton30Text: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: '#00a38b',
  },
  declineLink: {
    alignItems: 'center',
    paddingVertical: Spacing.xs,
  },
  declineText: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: '#d84a36',
    textDecorationLine: 'underline',
  },
});
