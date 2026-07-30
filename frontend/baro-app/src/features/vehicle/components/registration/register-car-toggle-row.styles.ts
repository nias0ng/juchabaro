import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    borderRadius: 20,
    backgroundColor: Palette.white,
    paddingHorizontal: Spacing.md,
    paddingVertical: 14,
    gap: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  texts: {
    flex: 1,
    gap: 2,
  },
  label: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  description: {
    fontSize: 10.5,
    color: Palette.gray500,
  },
});
