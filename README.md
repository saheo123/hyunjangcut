# 현장컷 홍보메이커

현장 사진과 제품만 고르면 티링크 공식 자료에 근거한 블로그 원고, 카드뉴스 4컷, 문자 문구를 만들고, 월간 가이드라인 준수 여부를 코드로 검수하는 도구.

## 구조
- `app.py` Streamlit 화면 (사진 업로드 → ① 사진 분석·차별점 → ② 콘텐츠 3종 → ③ 검수표)
- `ai.py` Google Gemini API 호출 2회 (사진 분석+매칭, 콘텐츠 생성). 무료 등급 키로 동작, 모델을 쓸 수 없으면 다음 모델로 자동 재시도
- `checker.py` 규칙 검수 (필수 키워드, 첫 문단 키워드, 미션 11개, 하단 정보, SMS 90byte, 팩트락, 개인 전화번호)
- `data/factsheet.json` 공식 자료 5종에서 뽑은 문장 33개와 출처 페이지
- `data/guideline_2026_11.json` 11월 가이드라인 규칙 (달마다 이 파일만 교체)
- `data/demo_result.json` API 키 없이 화면을 볼 수 있는 데모 결과

## 실행
```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 키 입력
streamlit run app.py
```
키가 없으면 사이드바의 데모 모드로 저장된 예시 결과가 나온다.

## 검수기 단독 테스트
```
python checker.py tests/demo_only_result.json   # 17/17, 확인 필요 0건
python checker.py tests/bad_result.json         # 지어낸 30%, 개인 번호, 없는 근거 ID → 확인 필요 3건
```

## 배포
GitHub에 올린 뒤 Streamlit Community Cloud에서 저장소를 연결하고, Secrets에 `GEMINI_API_KEY`를 넣는다.

## 실행 기록
생성할 때마다 `logs/history.csv`에 충족 항목 수, 확인 필요 건수, 단계별 소요 시간이 쌓인다. 2단계 실측 숫자는 이 파일에서 뽑는다.
