#!/usr/bin/env bash
# 폴더 일괄 변환 — backend 컨테이너 안에서 batch_convert.py 호출
# 출력: <OUT>/{원본폴더명}_txt/
#
# 사용:
#   bash convert_all_newschools.sh                        # 기본 (newschools)
#   bash convert_all_newschools.sh <NEW> <OUT>            # 다른 데이터셋
# 예:
#   bash convert_all_newschools.sh /app/external_data/newschool2 /app/external_data/raw/newschool2

set -u
NEW="${1:-/app/external_data/newschools}"
OUT="${2:-/app/external_data/raw/newschools}"

t_total_start=$(date +%s)
TOTAL_DIRS=0
TOTAL_OK=0
TOTAL_FAIL=0

for d in "$NEW"/*/; do
    name=$(basename "$d")
    out_dir="$OUT/${name}_txt"

    TOTAL_DIRS=$((TOTAL_DIRS + 1))
    echo ""
    echo "============================================================"
    echo "[$TOTAL_DIRS] $name"
    echo "============================================================"
    t0=$(date +%s)

    python /app/scripts/batch_convert.py "$d" "$out_dir" 2>&1 | tail -25

    t1=$(date +%s)
    echo "  소요: $((t1 - t0))s"
done

t_total_end=$(date +%s)
echo ""
echo "============================================================"
echo "전체 완료 — $TOTAL_DIRS 폴더 / $((t_total_end - t_total_start))s"
echo "============================================================"
