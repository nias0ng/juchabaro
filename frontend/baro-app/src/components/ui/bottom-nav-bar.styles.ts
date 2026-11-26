import { StyleSheet } from 'react-native';

import { MaxContentWidth, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    container: {
      width: '100%',
      borderTopWidth: 1,
      paddingTop: 12,
      paddingBottom: 8,
    },
    tabsRow: {
      flexDirection: 'row',
      width: '100%',
      maxWidth: MaxContentWidth,
      alignSelf: 'center',
    },
    tab: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 1,
    },
    homeTab: {
      gap: 0,
    },
    iconContainer: {
      width: 24,
      height: 24,
      alignItems: 'center',
      justifyContent: 'center',
    },
    badge: {
      position: 'absolute',
      top: -2,
      right: -2,
      width: 6,
      height: 6,
      borderRadius: 3,
      backgroundColor: t.fill.error.strong,
    },
    label: {
      fontSize: 11,
      textAlign: 'center',
    },
  });
