import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.base,
    backgroundColor: Palette.white,
    borderRadius: Radius.input,
    padding: Spacing.base + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  photoSlot: {
    width: 56,
    height: 56,
    borderRadius: Radius.md + 2,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: 'rgba(20, 22, 28, 0.35)',
    backgroundColor: 'rgba(127, 127, 127, 0.08)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  photoSlotText: {
    fontSize: 13,
    fontWeight: FontWeight.medium,
    color: Palette.gray975,
    textAlign: 'center',
    opacity: 0.75,
  },
  info: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
