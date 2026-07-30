import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  complexCard: {
    width: '100%',
    borderRadius: 22,
    padding: 18,
    gap: Spacing.base,
  },
  complexHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  complexIconBadge: {
    width: 24,
    height: 24,
    borderRadius: 8,
    backgroundColor: 'rgba(255,255,255,0.85)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  complexIconText: {
    fontSize: 11,
  },
  complexName: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  unitRow: {
    flexDirection: 'row',
    gap: Spacing.sm,
    width: '100%',
    height: 53,
  },
  unitField: {
    flex: 1,
    height: '100%',
    borderRadius: 16,
    backgroundColor: 'rgba(255,255,255,0.9)',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.base,
  },
  unitInput: {
    flex: 1,
    fontSize: 18,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
    padding: 0,
  },
  unitSuffix: {
    fontSize: 12,
    color: Palette.gray500,
  },
  verificationLabel: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  verificationOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    borderRadius: Radius.input,
    borderWidth: 1,
    borderColor: 'transparent',
    backgroundColor: Palette.white,
    paddingHorizontal: 17,
    paddingVertical: 16,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  verificationOptionSelected: {
    borderColor: Palette.violet500,
  },
  verificationOptionLabel: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  radio: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: Palette.gray300,
  },
  radioSelected: {
    borderColor: Palette.violet500,
    borderWidth: 5,
  },
  verificationHelper: {
    fontSize: 10.5,
    color: Palette.gray500,
  },
});
