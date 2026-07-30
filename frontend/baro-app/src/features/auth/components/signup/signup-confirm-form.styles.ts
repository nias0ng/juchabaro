import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  reviewCard: {
    width: '100%',
    borderRadius: Radius.input,
    backgroundColor: Palette.white,
    paddingHorizontal: 17,
    paddingVertical: 15,
    gap: Spacing.sm,
    ...Shadows.control,
  },
  reviewCardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  reviewCardTitle: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  reviewEditLink: {
    fontSize: 11,
    color: Palette.violet500,
  },
  reviewRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
  },
  reviewRowLabel: {
    fontSize: 12.5,
    color: Palette.gray500,
  },
  reviewRowValue: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  agreementAllLabel: {
    fontSize: 12,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  agreementItemLabel: {
    fontSize: 11,
    fontWeight: FontWeight.regular,
    color: Palette.gray500,
  },
});
