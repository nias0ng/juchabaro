import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    padding: Spacing.md + 2,
    gap: Spacing.base + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerLabel: {
    fontSize: 12.5,
    color: '#9599a7',
  },
  headerValue: {
    fontSize: 15,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
  },
  row: {
    flexDirection: 'row',
    gap: Spacing.sm + 2,
  },
  dotColumn: {
    width: 9,
    alignItems: 'center',
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 4.5,
    backgroundColor: Palette.emerald500,
  },
  dotFinal: {
    backgroundColor: '#7a6ff0',
  },
  line: {
    flex: 1,
    width: 2,
    marginTop: Spacing.xxs,
    backgroundColor: '#e2e0ec',
  },
  textColumn: {
    flex: 1,
    gap: Spacing.xxs,
  },
  textColumnSpaced: {
    paddingBottom: Spacing.base,
  },
  stepLabel: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  stepLabelFinal: {
    color: '#7a6ff0',
  },
  stepDetail: {
    fontSize: 11,
    color: '#9599a7',
  },
});
