/* api 실패 전용 에러 
   - 서버가 알려준 에러와 코드 버그로 터진 에러를 구분
*/ 
export class ApiError extends Error {
  status: number; // HTTP 상태 코드 (400, 401, 403 등)
  code?: number; // 서버가 내려준 비즈니스 코드 (명세의 code 필드)

  constructor(message: string, status: number, code?: number) {
    super(message); // message는 화면에 그대로 보여줄 서버 에러 메시지
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}
