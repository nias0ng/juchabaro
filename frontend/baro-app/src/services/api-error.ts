/** API 요청 실패를 나타내는 에러. status/code로 서버가 알려준 실패와 네트워크/코드 오류를 구분한다. */
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
