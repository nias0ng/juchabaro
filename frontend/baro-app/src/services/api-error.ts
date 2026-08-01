/* api 실패 전용 에러 
   - 서버가 알려준 에러와 코드 버그로 터진 에러를 구분
*/ 
export class ApiError extends Error {
  status: number;
  code?: number;

  constructor(message: string, status: number, code?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}
