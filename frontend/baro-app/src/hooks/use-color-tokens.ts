import { useIsAdaptiveColorScope } from '@/hooks/adaptive-color-scope';
import { useColorScheme } from '@/hooks/use-color-scheme';
import type { ColorTokens } from '@/styles';

import { resolveColorTokens } from './resolve-color-tokens';

/** 용도 기반 색상 토큰. 다크 값은 AdaptiveColorScope 안에서만 나온다. */
export function useColorTokens(): ColorTokens {
  return resolveColorTokens(useIsAdaptiveColorScope(), useColorScheme());
}
