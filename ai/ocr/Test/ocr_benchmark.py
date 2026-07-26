'''
번호판 OCR에 사용할 모델을 선정하기 위해
EasyOCR,
PaddleOCR 한국어 PP-OCRv5 Mobile,
PaddleOCR PP-OCRv5 Server를 비교해보고 싶어 구현했습니다.

번호판 영역 검출(객체 검출)은 별도의 YOLOv8n-pose모델이 담당하므로,
각 모델은 recognition-only 방식으로 사용합니다.
따라서 각 프레임워크에 포함된 텍스트 검출기는 비교 대상에서 제외되며,
비교 결과에는 번호판 이미지에 대한 문자 인식 성능만 반영됩니다.
'''