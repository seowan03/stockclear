1. 기능적/기술적 완성도
🔴 치명적 — 프론트-백엔드 API 불일치
app.js는 /api/dashboard, /api/inventory, /api/inventory/{id}, /api/strategy, /api/export 를 호출하지만, 실제 백엔드(main.py, router.py)에는 이 엔드포인트들이 하나도 구현되어 있지 않습니다. 현재 백엔드는 /api/auth/*, /api/upload, /api/history, /api/ai-diagnose만 존재합니다. 즉 대시보드·재고 목록·전략·내보내기 화면은 모두 404가 나는 상태로, README의 "대시보드에서 직관적으로 제공" 주장과 실제 구현 사이 괴리가 큽니다.

🔴 업로드해도 분석 결과가 저장되지 않음
main.py의 /api/upload는 analyze_inventory() 결과를 응답으로만 반환하고, RawInventory/AnalysisResult 테이블(models.py에 정의는 있음)에는 저장하지 않습니다. 위에서 없다고 한 /api/dashboard, /api/inventory 등을 나중에 구현하더라도 조회할 데이터 자체가 DB에 없는 구조입니다. "저장 → 조회"로 이어지는 파이프라인이 끊겨 있습니다.

🟠 보안
비밀번호는 werkzeug로 해시하지만, 세션은 session_user 쿠키에 user_id를 평문으로 담아 서명/암호화 없이 사용 중입니다(main.py SESSION_COOKIE_NAME). 쿠키 값만 조작하면 다른 사용자로 위장할 수 있어 서버 사이드 세션(예: itsdangerous 서명, JWT, 또는 세션 스토어)로 교체가 필요합니다.
CORS에 allow_credentials=True + 로컬 origin만 허용되어 있어 배포 시 실제 프론트 도메인 반영이 누락되기 쉽습니다.
/api/ai-diagnose(router.py)는 인증 의존성(get_current_user)이 없어 로그인 없이도 호출 가능합니다.
OPENAI_API_KEY 등 비밀키는 .env로 분리되어 있고 .gitignore에도 포함되어 있는 점은 좋습니다. 다만 키 미설정 시 llm.py가 즉시 명확한 에러를 내지 않고 조용히 실패할 수 있습니다.
🟠 예외처리/데이터 검증
analysis.py는 입고일 파싱 실패 시 전체 업로드를 ValueError로 실패시키는데, 원가가 0이거나 판매량이 없는 경우는 각각 처리하지만 음수 재고량/원가, 중복 컬럼명, 대용량 파일(행 수 제한, 업로드 용량 제한 없음) 등은 검증되지 않습니다.
df.apply(..., axis=1)로 행 단위 람다 연산을 하고 있어 대량 데이터에서 성능 저하가 발생할 수 있습니다(벡터화 연산으로 대체 가능).
llm.py의 response_format={"type:json_object"}는 오타로 보입니다(정상은 {"type": "json_object"}). 현재 코드로는 OpenAI structured output이 적용되지 않고 파싱 실패 시 예외 문구를 그대로 사용자에게 반환합니다.
파일 끝의 get_ai_startegy = get_ai_strategy 별칭이 함수 내부에 들여쓰기되어 있어 실행 시 정의되지 않는(dead code) 상태입니다 — 실제로 router.py의 try/except ImportError 폴백 로직이 무의미합니다.
🟡 확장성
DB 마이그레이션이 Base.metadata.create_all + 수동 ALTER TABLE(app/database.py ensure_upload_files_user_id_column)로 처리되어, 스키마 변경 시마다 함수를 추가해야 하는 구조입니다. Alembic 같은 정식 마이그레이션 도구 도입이 필요합니다.
테스트 코드가 전혀 없습니다(tests/ 디렉터리 부재). 핵심 로직(재고 분석 공식, 중복 업로드 판정)에 대한 단위 테스트가 없어 회귀 위험이 큽니다.
2. README 가독성 및 정보 부족
설치/실행 방법이 없습니다. pip install -r requirements.txt, .env 필요 변수 목록(DB_HOST, OPENAI_API_KEY 등), uvicorn app.main:app --reload 같은 실행 커맨드가 README에 전혀 없습니다. 처음 보는 사람은 프로젝트를 실행조차 할 수 없습니다.
API 문서/엔드포인트 목록 부재. FastAPI가 자동 생성하는 /docs(Swagger) 링크 안내도 없고, README에 REST API 스펙 요약도 없습니다.
필수 업로드 컬럼 명세 부재. 실제로는 상품명, 재고량, 원가, 입고일, 판매가, 판매량 6개 컬럼이 필수(main.py)인데 README에는 언급이 없어, 사용자가 어떤 형식의 엑셀을 준비해야 하는지 알 수 없습니다.
스크린샷/데모 GIF 없음. 대시보드나 업로드 화면 이미지가 없어 비개발자가 결과물을 가늠하기 어렵습니다.
환경변수 예시 파일 부재. .env.example 같은 템플릿이 없어 신규 기여자가 어떤 값을 채워야 하는지 추측해야 합니다.
시스템 구조 다이어그램은 좋으나, 실제 구현 상태(예: LLM 연동은 부분적으로만 동작, 대시보드 API는 미구현)와 다이어그램이 암시하는 완성도 사이 괴리를 README가 명시하지 않아 오해를 줄 수 있습니다.
라이선스 섹션이 없습니다.
3. 추천 Next Step
API 정합성 복구: /api/dashboard, /api/inventory, /api/strategy, /api/export를 실제로 구현하고, 업로드 시 분석 결과를 RawInventory/AnalysisResult에 저장하는 파이프라인을 완성해야 프론트가 정상 동작합니다. 우선순위 1순위로 두는 걸 권장합니다.
.env.example 추가 및 README에 "설치 → 환경변수 설정 → 실행 → 접속(/docs, /)" 순서의 Quick Start 섹션 작성.
세션/인증 강화: 서명된 세션 쿠키 또는 JWT 도입, 보호가 필요한 엔드포인트에 Depends(get_current_user) 일괄 적용.
테스트 스위트 도입: pytest + analyze_inventory() 단위 테스트, /api/upload 통합 테스트부터 시작.
CI 파이프라인(GitHub Actions)으로 lint/test 자동화 — 협업 팀 규모(5명)를 고려하면 우선순위가 높습니다.
엑셀 템플릿 다운로드 기능: 사용자가 올바른 컬럼 형식을 맞추도록 샘플 엑셀 제공.
알림/리마인더 기능: 처분 권장 등급 재고에 대한 이메일/슬랙 알림 등, 실무 활용도를 높이는 기능.
Docker화: Dockerfile + docker-compose.yml(FastAPI + MySQL)로 배포/온보딩 단순화.