import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(20, 22, 28, 0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  sheet: {
    width: '100%',
    maxWidth: 360,
    borderRadius: 26,
    backgroundColor: Palette.white,
    padding: Spacing.lg,
    gap: Spacing.base,
    shadowColor: 'rgba(20, 22, 28, 0.18)',
    shadowOffset: { width: 0, height: 20 },
    shadowOpacity: 1,
    shadowRadius: 22,
    elevation: 6,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  closeIcon: {
    fontSize: 16,
    color: Palette.gray500,
  },
  subtitle: {
    fontSize: 12,
    color: Palette.gray500,
  },
});
