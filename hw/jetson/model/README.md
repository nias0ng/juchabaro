# Jetson Tracking Model

운영 차량 추적 모델은 `yolov8s.pt`다. 저장소 checkout에서는 다음 위치를
사용한다.

```text
hw/jetson/model/yolov8s.pt
```

Jetson 배포 시에는 다음 절대경로에 같은 파일을 배치한다.

```text
/home/e202/model/yolov8s.pt
```

모델 가중치는 Git에 포함하지 않는다. Viewer 실행 또는 Jetson 기동 전에 해당
환경의 경로에 `yolov8s.pt`를 직접 배치해야 한다.
