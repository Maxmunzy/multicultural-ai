import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

# 2. 모델 설정 (허락 필요 없는 한국어 특화 모델)
model_id = "MLP-KTLim/llama-3-Korean-Bllossom-8B"

# 3. 4-bit 양자화 설정 (이게 핵심입니다!)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16
)

# 4. 모델 로드 (quantization_config를 사용합니다)
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    quantization_config=bnb_config, # 에러 났던 부분을 이렇게 수정했어요!
    device_map="auto",
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)

# 5. 통합 추출 함수 정의
def analyze_notice(text):
    prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>
당신은 학교 가정통신문 분석 전문가입니다. 아래 규칙에 따라 '할 일'을 추출하세요.
결과는 반드시 JSON 리스트 형식으로만 출력하세요.

[카테고리] "일정", "준비물", "제출", "비용", "건강·안전", "기타"

입력: "4월 20일까지 체험학습 신청서를 제출하고, 개인 물병을 준비하세요."
출력: [
    {{"category": "제출", "text_ko": "체험학습 신청서 제출", "due_date": "04-20", "importance": 0.9, "text_vi": ""}},
    {{"category": "준비물", "text_ko": "개인 물병 지참", "due_date": null, "importance": 0.7, "text_vi": ""}}
]<|eot_id|><|start_header_id|>user<|end_header_id|>
입력: {text}<|eot_id|><|start_header_id|>assistant<|end_header_id|>"""

    inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
    
    # 모델 답변 생성
    with torch.no_grad():
        outputs = model.generate(
            **inputs, 
            max_new_tokens=512, 
            temperature=0.1,
            do_sample=True,
            eos_token_id=tokenizer.eos_token_id
        )
    
    result = tokenizer.decode(outputs[0], skip_special_tokens=True)
    # 모델의 답변 부분만 파싱
    final_output = result.split("assistant")[-1].strip()
    return final_output

# 테스트 실행
print("--- 분석 결과 ---")
print(analyze_notice("5월 15일은 스승의 날입니다. 감사의 마음을 담은 편지를 준비해 주세요."))

import pandas as pd
import json

# 1. 파일 읽기
df = pd.read_csv('notices_labeled_v2.csv') 

final_output = []

# 2. 27개 데이터 반복 처리 (시간이 좀 걸릴 수 있어요!)
print("분석 시작...")
for index, row in df.iterrows():
    text = row['original_text'] # CSV 파일에 텍스트가 들어있는 컬럼명
    result = analyze_notice(text)
    
    try:
        # 결과를 JSON 객체로 변환해서 리스트에 담기
        parsed_result = json.loads(result)
        final_output.append({
            "notice_id": index,
            "todos": parsed_result
        })
        print(f"{index+1}번 공문 완료!")
    except:
        print(f"{index+1}번 공문 분석 중 에러 발생 (JSON 형식이 아님)")

# 3. 파일로 저장
with open('extracted_results.json', 'w', encoding='utf-8') as f:
    json.dump(final_output, f, ensure_ascii=False, indent=4)

print("모든 분석 완료! 'extracted_results.json' 파일을 다운로드하세요.")