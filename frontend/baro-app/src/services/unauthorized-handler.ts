type UnauthorizedHandler = () => void | Promise<void>;

let unauthorizedHandler: UnauthorizedHandler | null = null;
let handlingUnauthorized: Promise<void> | null = null;

/**
 * React 바깥의 HTTP 클라이언트가 인증 상태 관리자에게 401을 전달할 수 있게 한다.
 * 반환된 함수를 호출하면 현재 등록한 핸들러만 안전하게 해제한다.
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): () => void {
  unauthorizedHandler = handler;

  return () => {
    if (unauthorizedHandler === handler) {
      unauthorizedHandler = null;
    }
  };
}

/**
 * 동시에 여러 요청이 401이어도 세션 만료 처리는 한 번만 실행한다.
 */
export async function handleUnauthorized(): Promise<void> {
  if (!unauthorizedHandler) return;

  if (!handlingUnauthorized) {
    handlingUnauthorized = Promise.resolve(unauthorizedHandler()).finally(() => {
      handlingUnauthorized = null;
    });
  }

  await handlingUnauthorized;
}
