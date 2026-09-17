# StockClear 동적 웹페이지 재구축 프롬프트

## 프로젝트 실행 구조와 공통 구현 규칙
README.md의 실행 구조를 따른다.

```text
사용자 -> HTML / CSS / JavaScript -> FastAPI (app/main.py) -> Pandas 분석 (app/analysis.py)
	-> 재고 위험도 판정 -> MySQL 저장 (SQLAlchemy 모델) -> OpenAI LLM 전략 추천 (app/llm.py)
	-> 대시보드 / 재고 / 전략 / 리포트 렌더링
```

구현 규칙
- `static`에 HTML을 만들고, 공통 스타일은 `static/style.css`, 공통 동작은 `static/app.js`로 분리한다.
- HTML에는 재고 KPI, 상품, 이력, AI 전략을 하드코딩하지 않는다. `fetch`로 FastAPI `/api/*`를 호출해 사용자별 데이터를 렌더링한다.
- `GET /api/auth/me`으로 세션 쿠키 로그인 상태를 검사하고, 보호 페이지에서 비로그인 사용자는 `signin.html`로 이동한다.
- 모든 API 호출에 로딩, 빈 데이터, 401, 400, 409, 500 오류 상태를 구현한다.
- `POST /api/upload`은 `FormData` 파일을 전송한다. 필수 컬럼은 `상품명`, `재고량`, `원가`, `입고일`, `판매가`, `판매량`이다.
- 업로드 후 `app/analysis.py`의 `analyze_inventory()`로 `storage_days`, `inventory_value`, `sales_speed`, `days_to_sell`, `depreciation_rate`를 계산하고, 결과를 `AnalysisResult`에 `RawInventory.item_id`와 연결해 저장한다.
- `router.py`의 AI 진단 라우터는 `app.include_router(router)`로 등록한다. `InventoryItem` 형식의 분석 데이터를 전달해 OpenAI LLM 결과를 저장하고 조회한다.
- 이미 구현된 인증, 업로드, 이력 API를 유지한다. 대시보드·재고·전략·내보내기에는 조회 API를 추가하고 모든 쿼리는 로그인 사용자의 데이터로 제한한다.

필수 API 계약
- `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`: 세션 기반 인증 처리.
- `POST /api/upload`: 원본 재고 저장, 분석 실행, `upload_batch_id`, `total_rows`, `saved_rows`, `data_preview` 반환.
- `GET /api/history`, `DELETE /api/history/{history_id}`, `DELETE /api/history`: 사용자별 업로드 이력 관리.
- 추가 `GET /api/dashboard`: KPI, 재고 등급 분포, 위험 상품 목록 반환.
- 추가 `GET /api/inventory`, `GET /api/inventory/{item_id}`: 검색·상태·페이지네이션, 상품 상세·분석·AI 진단 반환.
- 추가 `GET /api/strategy`: 긴급 발주·장기 재고 프로모션 전략, 근거, 예상 효과 반환.
- 추가 `GET /api/export`: 동적 분석 리포트 데이터 반환.

## mainpage.html
기능
- StockClear AI 재고 최적화 서비스의 랜딩 페이지를 구성한다.
- 상단 내비게이션, 데이터 업로드 CTA, 샘플 대시보드 CTA를 제공한다.
- `GET /api/auth/me`으로 로그인 상태를 확인해 CTA를 `upload.html` 또는 `signin.html`로 연결한다.
- 엑셀/CSV 연동, 실시간 대시보드, AI 최적화 추천의 핵심 장점을 안내한다.

필수 키워드
- 홈페이지, 랜딩 페이지, AI 기반, 재고 최적화, 데이터 업로드, 대시보드, 세션 인증, API 연동

## signin.html
기능
- 로그인과 회원가입 탭을 제공한다.
- 로그인 시 `POST /api/auth/login`, 회원가입 시 `POST /api/auth/signup`을 JSON으로 호출한다.
- 성공 시 `upload.html`로 이동하고, 실패 시 응답의 `detail` 메시지를 표시한다.
- Google, Kakao OAuth API가 없으면 준비 중 상태로 표시하고 로그인 성공처럼 동작시키지 않는다.

필수 키워드
- 로그인, 회원가입, 이메일, 비밀번호, 사용자명, fetch, JSON, 세션 쿠키, 오류 메시지, 인증 API

## dashboard.html
기능
- 페이지 진입 시 `GET /api/dashboard`를 호출해 로그인 사용자의 최신 분석 결과를 렌더링한다.
- 총 SKU, 결품 위험, 60일 이상 장기 재고, 월 절감 예상액 KPI를 API 응답으로 표시한다.
- 재고 등급 분포 도넛 차트와 위험도 상위 상품 차트를 API 배열 데이터로 생성한다.
- 데이터가 없으면 파일 업로드 CTA를 표시하고 AI 전략 화면으로 이동하는 버튼을 제공한다.

필수 키워드
- 대시보드, 동적 데이터, dashboard API, KPI, 재고 등급, 도넛 차트, 위험도, 빈 상태, 로딩 상태, 사용자별 데이터

## inventory.html
기능
- 페이지 진입 및 검색어·상태 변경 시 `GET /api/inventory`를 호출한다.
- SKU 코드, 품목명, 현재 수량, 안전재고, 보관기간, 위험 등급, AI 추천 조치를 표로 렌더링한다.
- 검색, 상태 필터, 페이지네이션은 API 쿼리 파라미터와 동기화한다.
- 행 선택 시 `GET /api/inventory/{item_id}`로 상세 정보, 분석 결과, AI 진단, 판매 이력을 탭 모달에 표시한다.
- 삭제 기능은 사용자 소유권을 검증하는 백엔드 삭제 API와 함께 구현한다.

필수 키워드
- 재고 목록, inventory API, 검색, 상태 필터, 페이지네이션, item_id, 상품 상세 모달, 분석 결과, AI 진단, 판매 이력, 동적 테이블

## upload.html
기능
- 드래그 앤 드롭 또는 파일 선택으로 재고 파일을 입력받는다.
- 파일 선택 후 `POST /api/upload`에 `FormData`로 전송한다.
- 업로드 중 버튼을 비활성화하고 로딩 상태를 표시한다.
- 성공 시 파일명, `total_rows`, `saved_rows`, `data_preview`를 보여주고 `dashboard.html`로 이동할 수 있게 한다.
- 401은 로그인 화면으로 이동하고, 409는 중복 업로드 안내를 표시한다.

필수 키워드
- 파일 업로드, 드래그 앤 드롭, FormData, XLSX, XLS, CSV, 필수 컬럼, upload_batch_id, data_preview, 로딩 상태, 중복 업로드

## strategy.html
기능
- `GET /api/strategy`로 AI 분석 결과 기반 실행 전략을 불러온다.
- 안전재고 미달은 긴급 발주, 장기 재고는 할인·번들·프로모션 전략으로 구분한다.
- 전략별 대상 품목, 위험 등급, 권장 조치, 할인율, 예상 절감 효과, AI 판단 근거를 표시한다.
- 등록된 `POST /api/ai-diagnose`로 개별 품목 AI 진단을 생성하거나 갱신한다.
- 발주서 생성·프로모션 등록 API가 없으면 완료 메시지를 위조하지 않고 준비 중 상태로 표시한다.

필수 키워드
- AI 전략, strategy API, 긴급 발주, 안전재고 미달, 장기 재고, 할인율, 예상 절감 효과, OpenAI, AI 진단, 실행 계획

## history.html
기능
- 페이지 진입 시 `GET /api/history`로 사용자별 업로드 이력을 표시한다.
- 파일명 검색은 가져온 목록을 필터링하거나 백엔드 검색 파라미터와 연동한다.
- 업로드 일시, 파일명, 파일 용량, 성공·실패 상태를 API 응답으로 렌더링한다.
- 개별 삭제는 `DELETE /api/history/{history_id}`, 전체 삭제는 `DELETE /api/history` 후 목록을 다시 불러온다.

필수 키워드
- 업로드 기록, history API, 파일명 검색, 업로드 일시, 파일 용량, 처리 상태, 성공, 실패, DELETE, 사용자별 이력

## export.html
기능
- 페이지 진입 시 `GET /api/export` 또는 분석 조회 API로 최신 리포트 데이터를 불러온다.
- SKU 코드, 품목명, 재고 수량, 보관기간, 위험 등급, AI 추천 조치를 동적으로 표에 표시한다.
- AI 진단 요약은 실제 결품 위험 수, 장기 재고 수, 권장 할인율, 예상 절감액을 기반으로 생성한다.
- CSV와 XLSX 다운로드는 API 응답 데이터로 생성하고, 인쇄/PDF는 브라우저 인쇄 기능을 사용한다.

필수 키워드
- 내보내기, export API, 상세 분석, 리포트, 동적 테이블, AI 진단 요약, CSV 다운로드, XLSX 다운로드, 인쇄, PDF 저장
