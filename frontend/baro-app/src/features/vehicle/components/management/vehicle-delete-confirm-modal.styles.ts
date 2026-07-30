import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(20,22,28,0.5)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  sheet: {
    width: '100%',
    maxWidth: 344,
    borderRadius: 26,
    backgroundColor: Palette.white,
    paddingTop: 26,
    paddingHorizontal: 22,
    paddingBottom: 22,
    alignItems: 'center',
    shadowColor: 'rgba(20,22,28,0.18)',
    shadowOffset: { width: 0, height: 20 },
    shadowOpacity: 1,
    shadowRadius: 22,
    elevation: 6,
  },
  iconCircle: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: '#fff0eb',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 14,
  },
  iconText: {
    fontSize: 20,
    color: Palette.orange600,
  },
  title: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
    marginBottom: 12,
  },
  description: {
    fontSize: 11.5,
    color: '#9599a7',
    textAlign: 'center',
    lineHeight: 19.55,
    marginBottom: 14,
  },
  errorBanner: {
    width: '100%',
    borderRadius: Radius.md,
    paddingHorizontal: Spacing.base,
    paddingVertical: Spacing.sm,
    marginBottom: 12,
  },
  errorText: {
    fontSize: 12,
    textAlign: 'center',
  },
  actions: {
    width: '100%',
    gap: 8,
  },
  deleteButton: {
    height: 46,
    borderRadius: 14,
    backgroundColor: '#e5493d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  deleteButtonPressed: {
    backgroundColor: '#d13d31',
  },
  deleteButtonText: {
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
  cancelButton: {
    height: 42,
    borderRadius: 14,
    backgroundColor: '#f0eef8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelButtonPressed: {
    backgroundColor: '#e5e1ed',
  },
  cancelButtonText: {
    fontSize: 13,
    fontWeight: FontWeight.medium,
    color: '#5c6070',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
});
