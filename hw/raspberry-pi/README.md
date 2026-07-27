# Raspberry Pi Entry Service

주차장 입구의 차량 감지, 번호판 촬영 및 OCR을 담당한다.

## 실행 환경

- Python 3.13.5
- Debian GNU/Linux 13 (trixie)

## 처리 흐름

1. 프로그램 실행
2. OCR 모델 1회 로드
3. 초음파 센서 감지 대기
4. 차량 감지 시 카메라 촬영
5. 번호판 OCR 수행
6. OCR 결과를 Jetson으로 전송
7. 다시 센서 감지 대기

## 실행

`raspberry-pi` 폴더에서 실행한다.

```bash
python -m src.main