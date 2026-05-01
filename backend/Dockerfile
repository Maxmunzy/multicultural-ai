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
    && rm -rf /var/lib/apt/lists/*

RUN wget -O /tmp/h2orestart.oxt "${H2O_URL}" \
    && unopkg add --shared /tmp/h2orestart.oxt \
    && rm -f /tmp/h2orestart.oxt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
