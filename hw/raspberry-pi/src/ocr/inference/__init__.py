"""
OCR 파이프라인에서 사용하는 AI 모델 추론 adapter 패키지.

모델 파일은 서비스 시작 시 loader로 한 번 읽고, 생성된 detector와
reader 객체를 차량 이벤트마다 재사용한다. 영상 전처리와 결과 판정은
각각 ``vision``과 ``postprocessing`` 패키지가 담당한다.
"""
