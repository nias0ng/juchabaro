import { createContext, useContext, type ComponentType, type ReactNode } from 'react';

const AdaptiveColorContext = createContext(false);

/** 이 범위 안의 컴포넌트는 기기의 라이트/다크 모드를 따른다. */
export function AdaptiveColorScope({ children }: { children: ReactNode }) {
  return <AdaptiveColorContext.Provider value>{children}</AdaptiveColorContext.Provider>;
}

export function useIsAdaptiveColorScope(): boolean {
  return useContext(AdaptiveColorContext);
}

/**
 * 색을 모두 용도 기반 토큰으로 옮긴 화면을 감싼다.
 * 화면 컴포넌트 자신의 스타일도 범위 안에서 만들어지도록 화면 밖에서 감싸야 한다.
 *
 * ```ts
 * export default withAdaptiveColors(RequestsScreen);
 * ```
 */
export function withAdaptiveColors<P extends object>(Screen: ComponentType<P>) {
  function AdaptiveScreen(props: P) {
    return (
      <AdaptiveColorScope>
        <Screen {...props} />
      </AdaptiveColorScope>
    );
  }

  AdaptiveScreen.displayName = `withAdaptiveColors(${Screen.displayName ?? Screen.name})`;
  return AdaptiveScreen;
}
