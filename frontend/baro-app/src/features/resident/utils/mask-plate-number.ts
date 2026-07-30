/**
 * 차량 번호 마스킹 정책이 아직 확정되지 않아, 뒷자리 2자리를 가리는 보수적인 기본값으로 구현했다.
 * TODO(vehicle-privacy): 백엔드/기획에서 마스킹 정책이 확정되면 규칙을 다시 확인해야 함
 */
export function maskPlateNumber(plateNumber: string): string {
  const trimmed = plateNumber.trim();
  if (trimmed.length <= 2) return trimmed;

  return `${trimmed.slice(0, -2)}**`;
}
