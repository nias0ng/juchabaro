// ParkingEventListView/HistoryView가 각자 구현하던 CSV 다운로드 뼈대(이스케이프, UTF-8 BOM,
// Blob 생성, 다운로드 트리거)를 공용으로 뺐다. 컬럼 구성과 값 포맷팅(도메인 지식)은 호출하는
// 쪽에서 headers/rows로 만들어 넘긴다.
function escapeCsvValue(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export function downloadCsv(filename: string, headers: string[], rows: string[][]): void {
  const lines = [
    headers.map(escapeCsvValue).join(','),
    ...rows.map((row) => row.map(escapeCsvValue).join(',')),
  ];
  // Excel에서 한글이 깨지지 않도록 UTF-8 BOM을 앞에 붙인다.
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
