# OCR Slot Correction Eval

- input: `C:\Users\user\Desktop\project\TEAM\multicultural-ai\data\ocr_slot_correction_eval_sample.csv`
- cases: 7

## Summary

| metric | raw OCR | corrected |
|---|---:|---:|
| exact match | 1/7 (14%) | 7/7 (100%) |
| avg CER | 0.1282 | 0.0000 |

- correction_applied: 6/7
- review_required: 0/7

## Cases

| case | slot | raw | corrected | truth | pass | corrections |
|---|---|---|---|---|---|---|
| OCR-SLOT-001 | amount | 체험학습비는 44,B70완입니다. | 체험학습비는 44,870원입니다. | 체험학습비는 44,870원입니다. | OK | amount:44,B70완->44,870원 |
| OCR-SLOT-002 | time | 일시: 8:5O ~ 14:4O | 일시: 8:50 ~ 14:40 | 일시: 8:50 ~ 14:40 | OK | time:8:5O->8:50 | time:14:4O->14:40 |
| OCR-SLOT-003 | date | 5원 6일(묵)까지 제출 | 5월 6일(목)까지 제출 | 5월 6일(목)까지 제출 | OK | date:5원 6일->5월 6일 | weekday:(묵)->(목) |
| OCR-SLOT-004 | grade | 대상: l-6확년, 3밤 | 대상: 1-6학년, 3반 | 대상: 1-6학년, 3반 | OK | grade:l-6확년->1-6학년 | class:3밤->3반 |
| OCR-SLOT-005 | phone | 문의: O10-1234-567S | 문의: 010-1234-5675 | 문의: 010-1234-5675 | OK | phone:O10-1234-567S->010-1234-5675 |
| OCR-SLOT-006 | negative | B반 학생은 OpenClass로 이동 | B반 학생은 OpenClass로 이동 | B반 학생은 OpenClass로 이동 | OK |  |
| OCR-SLOT-007 | mixed | 5원 6일(묵) 8:5O까지 44,B70완 납부, 문의 O10-1234-567S | 5월 6일(목) 8:50까지 44,870원 납부, 문의 010-1234-5675 | 5월 6일(목) 8:50까지 44,870원 납부, 문의 010-1234-5675 | OK | date:5원 6일->5월 6일 | weekday:(묵)->(목) | time:8:5O->8:50 | amount:44,B70완->44,870원 | phone:O10-1234-567S->010-1234-5675 |
