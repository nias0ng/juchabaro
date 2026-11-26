import { useColorScheme } from '@/hooks/use-color-scheme';
import { Tokens, type ColorTokens } from '@/styles';

/** 현재 모드(라이트/다크)의 용도 기반 색상 토큰. */
export function useColorTokens(): ColorTokens {
  return useColorScheme() === 'dark' ? Tokens.dark : Tokens.light;
}
