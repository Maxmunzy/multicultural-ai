#!/bin/bash
set -u

INPUT_DIRS=(
    "/data/extra_500"
    "/data/extra_694"
    "/data/seongnam_pdfs"
    "/data/taepyeong_pdfs"
    "/data/extra_405"
    "/data/extra_1033"
)
OUTPUT_DIR="/data/converted_pdfs"
LOG="/data/convert.log"

mkdir -p "$OUTPUT_DIR"
: > "$LOG"

# Collect all HWP/HWPX (case-insensitive)
TMP_LIST="/tmp/hwp_list.txt"
: > "$TMP_LIST"
for d in "${INPUT_DIRS[@]}"; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 1 -type f \( -iname "*.hwp" -o -iname "*.hwpx" \) >> "$TMP_LIST"
done

TOTAL=$(wc -l < "$TMP_LIST")
echo "=== Total HWP/HWPX to convert: $TOTAL ===" | tee -a "$LOG"
echo "Output: $OUTPUT_DIR" | tee -a "$LOG"
echo "Start: $(date)" | tee -a "$LOG"

# Parallel conversion via xargs (4 workers, separate user profiles)
convert_one() {
    local hwp="$1"
    local stem
    stem=$(basename "$hwp")
    local out_pdf="$OUTPUT_DIR/${stem%.*}.pdf"
    if [ -f "$out_pdf" ]; then
        echo "SKIP (exists): $stem" >> "$LOG"
        return 0
    fi
    local pid=$$
    local profile="/tmp/lo_prof_$pid"
    mkdir -p "$profile"
    if timeout 90 libreoffice --headless \
        "-env:UserInstallation=file://$profile" \
        --convert-to pdf \
        --outdir "$OUTPUT_DIR" \
        "$hwp" >> "$LOG" 2>&1; then
        if [ -f "$out_pdf" ]; then
            echo "OK: $stem" >> "$LOG"
        else
            echo "FAIL (no output): $stem" >> "$LOG"
        fi
    else
        echo "FAIL (timeout/error): $stem" >> "$LOG"
    fi
}
export -f convert_one
export OUTPUT_DIR LOG

cat "$TMP_LIST" | xargs -I {} -P 4 bash -c 'convert_one "$@"' _ {}

echo "End: $(date)" | tee -a "$LOG"

# Summary
OK_COUNT=$(grep -c "^OK:" "$LOG" || echo 0)
SKIP_COUNT=$(grep -c "^SKIP" "$LOG" || echo 0)
FAIL_COUNT=$(grep -c "^FAIL" "$LOG" || echo 0)
PDF_COUNT=$(ls "$OUTPUT_DIR"/*.pdf 2>/dev/null | wc -l)
echo "=== Summary ===" | tee -a "$LOG"
echo "OK: $OK_COUNT, SKIP: $SKIP_COUNT, FAIL: $FAIL_COUNT" | tee -a "$LOG"
echo "PDFs in output: $PDF_COUNT" | tee -a "$LOG"
