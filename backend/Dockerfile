FROM python:3.11-slim

WORKDIR /app

# 파일 변환 의존: LibreOffice headless + H2Orestart 확장 + 한글 폰트.
# 학습 데이터 가공과 런타임 [1] 텍스트 변환 모두 사용.
# H2Orestart는 latest 채널 사용 — 버전별 asset 파일명이 일관되지 않아 latest/download 안전.
ARG H2O_URL=https://github.com/ebandal/H2Orestart/releases/latest/download/H2Orestart.oxt

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-java-common \
        default-jre-headless \
        fonts-nanum \
        fonts-noto-cjk \
        wget \
        ca-certificates \
        tesseract-ocr \
        tesseract-ocr-kor \
        libgl1 \
        git \
        build-essential \
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

RUN wget -O /tmp/h2orestart.oxt "${H2O_URL}" \
    && unopkg add --shared /tmp/h2orestart.oxt \
    && rm -f /tmp/h2orestart.oxt

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=600 -r requirements.txt

# LayoutLMv2 (LayoutXLM backbone)는 detectron2 의존성 필요 — Hybrid sentence_extraction 모델용
# 표 EAV 추출용 camelot + opencv-python-headless (cv2 의존)도 영구 설치
RUN pip install --no-cache-dir --default-timeout=600 \
        camelot-py \
        opencv-python-headless \
    && pip install --no-cache-dir --default-timeout=600 'git+https://github.com/facebookresearch/detectron2.git'

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
