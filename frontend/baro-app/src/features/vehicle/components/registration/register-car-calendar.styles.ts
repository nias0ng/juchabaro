import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

const CELL_WIDTH_PERCENT = '14.2857%';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    gap: Spacing.sm,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  navButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Palette.gray100,
    transform: [{ translateY: -2 }],
  },
  navIcon: {
    width: 28,
    fontSize: 15,
    lineHeight: 28,
    textAlign: 'center',
    color: Palette.gray975,
  },
  headerTitle: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  weekdayRow: {
    flexDirection: 'row',
  },
  weekdayLabel: {
    width: CELL_WIDTH_PERCENT,
    textAlign: 'center',
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: Palette.gray400,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  cell: {
    width: CELL_WIDTH_PERCENT,
    aspectRatio: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dayCircle: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dayCircleSelected: {
    backgroundColor: Palette.violet500,
  },
  dayText: {
    fontSize: 12.5,
    color: Palette.gray975,
  },
  dayTextSelected: {
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
});
