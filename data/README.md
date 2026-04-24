# Data Guide

## 목적
가정통신문 원문에서 학부모가 실제로 행동해야 하는 핵심 정보를 추출하기 위한 데이터입니다.

## 주요 카테고리
- 일정
- 준비물
- 제출
- 비용
- 건강/안전
- 생활지도
- 학습
- 일반공지

## 중요도 기준
- 1.0: 오늘/내일 바로 행동 필요
- 0.9: 준비물/제출/납부처럼 놓치면 문제가 생기는 정보
- 0.7: 일정 확인이 필요한 정보
- 0.5: 생활지도/학습 관련 참고 정보
- 0.3: 일반 안내

## 파일 구조
- raw/: 원본 가정통신문 텍스트
- labeled/: 라벨링된 문장 단위 데이터

## 라벨링 컬럼
id, source_type, original_text, category, keywords, importance, action_required, easy_korean, vietnamese, tts_target