# HF Spaces Docker SDK — schoolbridge 백엔드
# build context = repo root (backend/ + model/ 전부 포함)
FROM python:3.11-slim

WORKDIR /app

# 파일 변환 의존 (HWP → 텍스트, PDF, 이미지 OCR)
# H2Orestart는 latest 채널 사용 — 버전별 asset 파일명 안전성 확보
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
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

RUN wget -O /tmp/h2orestart.oxt "${H2O_URL}" \
    && unopkg add --shared /tmp/h2orestart.oxt \
    && rm -f /tmp/h2orestart.oxt

# Python 의존 설치 (CPU torch + transformers + edge-tts 등)
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 백엔드 코드
COPY backend/app /app/app

# 외부 모델 코드 (분류기·추출기 src/) — 가중치는 HF Hub에서 자동 다운로드
COPY model /app/external_model

# 정적 디렉토리 (TTS mp3, 가통문 원본 PDF/이미지)
RUN mkdir -p /app/static/tts /app/static/notices \
    && chmod -R 777 /app/static

# HF Spaces 기본 포트 7860 — 도메인 https://{user}-{space}.hf.space 로 자동 매핑
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
