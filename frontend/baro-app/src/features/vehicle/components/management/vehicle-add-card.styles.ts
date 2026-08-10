import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    alignItems: 'center',
    gap: 6,
    padding: 21,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: '#d5d8e2',
    borderStyle: 'dashed',
  },
  containerPressed: {
    backgroundColor: Palette.gray50,
  },
  iconCircle: {
    width: 34,
    height: 34,
    borderRadius: 12,
    backgroundColor: '#f0eef8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconPlus: {
    fontSize: 16,
    color: '#9599a7',
  },
  title: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  subtitle: {
    fontSize: 11,
    color: '#9599a7',
  },
});
