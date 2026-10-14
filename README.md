# 📦 StockClear

> **기업의 숨은 자금을 찾아주는 스마트한 재고 파트너**

**StockClear**는 Excel/CSV 재고 데이터를 업로드하면 장기·악성 재고를 식별하고,
재고 위험도를 시각화하며, LLM으로 **상품별 재고 처분 전략**을 제안하는 재고 관리 웹 서비스입니다.

---

## 👥 팀 구성

| 역할 | 이름 |
|---|---|
| 팀장 | 임서환 |
| 팀원 | 김태호 |
| 팀원 | 이병우 |
| 팀원 | 박지훈 |
| 팀원 | 양상명 |

---

## 📌 프로젝트 소개

판매가 지연된 재고가 장기간 보관되면 보관 비용 증가, 자금 회수 지연, 상품 가치 하락, 관리 비효율이 발생합니다.
StockClear는 업로드된 재고 데이터를 Pandas로 분석해 **위험점수(0~100)** 와 **4단계 위험등급**을 산출하고,
대시보드·재고 목록·전략 화면에서 결과를 확인하고 조치할 수 있도록 지원합니다.

### 주요 기능

- **회원 인증**: 회원가입 / 로그인 / 로그아웃 / 비밀번호 재설정, 서명된 HttpOnly 세션 쿠키
- **재고 업로드**: `.xlsx`, `.csv` 업로드 및 검증, 업로드 후 AI 분석 요약 생성(실패 시 재시도)
- **재고 분석**: 보관기간, 재고금액, 판매속도, 예상소진기간, 감가율(원가 대비 판매가 차이), 위험점수/위험등급 계산
- **대시보드**: 위험등급별 현황, 판매 인사이트
- **재고 관리**: 목록 조회·일괄 수정·삭제, 판매 상태 전환, 일별 판매 지표, 안전재고 계산, 모의 시세 갱신
- **AI 진단 / 전략**: 상품별 LLM 진단, 처분 전략 조회 및 조치 기록
- **업로드 이력**: 이력 조회 및 삭제
- **내보내기**: 분석 결과 내보내기
- **고객센터**: 문의 등록, 답변 조회 / 관리자 문의 관리 및 답변

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|---|---|
| 프론트엔드 | HTML, CSS, JavaScript (정적 파일, FastAPI에서 서빙) |
| 백엔드 | Python, FastAPI, Uvicorn |
| 데이터 분석 | Pandas, NumPy |
| 데이터베이스 | MySQL, PyMySQL, SQLAlchemy |
| AI / LLM | OpenAI API (기본 모델 `gpt-4o-mini`) |
| 데이터 검증 | Pydantic |
| 파일 처리 | OpenPyXL, Python-Multipart |
| 보안 | Werkzeug(비밀번호 해시), itsdangerous(세션 서명) |
| 환경 설정 | Python-dotenv |
| 협업 | Git, GitHub, VS Code |

---

## 📁 프로젝트 구조

```text
stockclear/
├── app/
│   ├── main.py              # FastAPI 앱, 라우터 등록, 정적 파일 마운트
│   ├── config.py            # 환경 변수 및 상수(업로드 제한, CORS, 위험등급 메타)
│   ├── database.py          # SQLAlchemy 엔진/세션
│   ├── models.py            # ORM 모델
│   ├── schemas.py           # Pydantic 스키마
│   ├── security.py          # 세션 쿠키, 인증/관리자 의존성, 캐시 헤더 미들웨어
│   ├── analysis.py          # 재고 분석 및 위험도 산정, 안전재고 계산
│   ├── llm.py               # OpenAI 호출, 동시성 제한, 응답 검증
│   ├── routers/             # auth, upload, history, inventory, ai, inquiries, admin_inquiries
│   ├── services/            # 업로드/재고/일별 지표/모의 시세 서비스
│   └── utils/
│       └── file_validation.py  # 업로드 크기·형식·인코딩 검증
├── static/                  # HTML 페이지, css/, js/, sellpage/
├── requirements.txt
└── README.md
```

---

## 🏗️ 시스템 흐름

```text
사용자 (브라우저)
   │  Excel / CSV 업로드
   ▼
[1. FastAPI 파일 검증]
   └── 확장자, 시그니처, 크기, 인코딩, 필수 컬럼
   ▼
[2. Pandas · NumPy 분석]
   ├── 보관기간 / 재고금액 / 판매속도
   ├── 예상소진기간 / 감가율(원가 대비 판매가 차이)
   └── 위험점수 → 위험등급 (정상 · 주의 · 장기 · 악성)
   ▼
[3. MySQL 저장] (단일 트랜잭션)
   └── 업로드 이력 · 재고 원본 · 분석 결과 · 일별 지표
   ▼
[4. OpenAI LLM 업로드 요약]
   └── 실패 시 실패 상태 저장 → 재시도 가능
   ▼
 대시보드 / 재고 목록 / 전략 / 내보내기
   └── 상품별 AI 진단은 사용자가 요청할 때 생성
```

---

## 📊 분석 로직

### 업로드 파일 형식

| 항목 | 내용 |
|---|---|
| 확장자 | `.xlsx`, `.csv` (CSV 인코딩: UTF-8(BOM 포함) 또는 CP949) |
| 최대 크기 | 10MB |
| 최대 행 수 | 50,000행 |
| 필수 컬럼 | `상품명`, `재고량`, `원가`, `입고일`, `판매가`, `판매량` |

`재고량`, `원가`, `판매가`, `판매량`은 음수일 수 없으며, `입고일`은 날짜로 변환 가능해야 합니다.

### 계산 항목

| 항목 | 계산식 |
|---|---|
| 보관기간 | 오늘 − 입고일 (최소 0일) |
| 재고금액 | 재고량 × 원가 |
| 판매속도 | 판매량 ÷ 보관기간 |
| 예상소진기간 | 재고량 ÷ 판매속도 (판매속도 0이면 9999) |
| 감가율(원가 대비 판매가 차이) | (원가 − 판매가) ÷ 원가 × 100 |

### 위험점수 (0~100)

| 구성 요소 | 최대 점수 | 산식 |
|---|---|---|
| 보관기간 점수 | 40 | min(보관기간 ÷ 90 × 40, 40) |
| 회전 점수 | 30 | min(예상소진기간 ÷ 180 × 30, 30) |
| 감가 점수 | 30 | clip(감가율 ÷ 50 × 30, 0, 30) |

> 초기 기획의 시세변동률·재고금액 비중 지표는 실제 시세 데이터가 없어 위험점수 산정에서 제외했습니다.

### 위험등급

| 등급 | 위험점수 | 의미 |
|---|---|---|
| 🟢 정상 | 25 미만 | 정상 운영 대상 |
| 🟡 주의 | 25 이상 | 모니터링 대상 |
| 🟠 장기 | 45 이상 | 장기 관리 대상 |
| 🔴 악성 | 70 이상 | 우선 조치 대상 |

### 안전재고

```text
안전재고 = (최대 일판매량 × 최대 리드타임) − (평균 일판매량 × 평균 리드타임)
```

결과가 0 이하이면 `평균 일판매량 × 평균 리드타임`을 사용하며, 기본 리드타임은 최대 5일 / 평균 2일입니다.

### 일별 판매 지표 (더미 데이터)

업로드 시 품목별로 입고일부터 **31일간의 일별 판매량·잔여재고·판매가**를 생성해 `inventory_daily_metrics`에 저장합니다.
이 값은 실제 주문 기록이 아닌 **결정적(seed 기반) 더미 데이터**이며, 일 판매가는 기준 판매가의 ±5% 범위에서 변동합니다.
모의 시세 역시 판매가의 ±10% 범위(100원 단위)에서 생성되는 더미 값입니다.

---

## 🔌 API 개요

| 구분 | 엔드포인트 |
|---|---|
| 인증 | `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`, `POST /api/auth/reset-password`, `GET /api/auth/me` |
| 업로드 | `POST /api/upload`, `POST /api/upload/{upload_id}/summary/retry` |
| 이력 | `GET /api/history`, `DELETE /api/history`, `DELETE /api/history/{history_id}` |
| 대시보드 | `GET /api/dashboard`, `GET /api/dashboard/sales-insights` |
| 재고 | `GET /api/inventory`, `PATCH /api/inventory/batch`, `GET /api/inventory/daily`, `GET·DELETE /api/inventory/{item_id}`, `PATCH /api/inventory/{item_id}/selling`, `POST /api/inventory/selling`, `POST /api/inventory/{item_id}/refresh-market-price`, `GET·POST /api/inventory/{item_id}/safety-stock` |
| AI | `POST /api/ai-diagnose`, `POST /api/inventory/{item_id}/ai-diagnose` |
| 전략 | `GET /api/strategy`, `GET·POST /api/strategy/actions` |
| 내보내기 | `GET /api/export` |
| 고객 문의 | `POST /api/inquiries`, `GET /api/inquiries/{inquiry_id}/reply` |
| 관리자 문의 | `GET /api/admin/inquiries`, `PATCH /api/admin/inquiries/{inquiry_id}` |

서버 실행 후 `http://localhost:8000/docs`에서 Swagger 문서를 확인할 수 있습니다.

---

## 🚀 실행 방법

### 1. 의존성 설치

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 환경 변수 설정 (`.env`)

프로젝트 루트에 `.env` 파일을 생성합니다. **실제 비밀번호·API 키는 Git에 커밋하지 마세요.**

```dotenv
ENV=development

# DATABASE_URL을 지정하면 아래 DB_* 값보다 우선 적용됩니다.
# DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname?charset=utf8mb4
DB_HOST=your-db-host
DB_PORT=3306
DB_USER=your-db-user
DB_PASSWORD=your-db-password
DB_NAME=your-db-name
DB_CHARSET=utf8mb4

OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini

# ENV=production이면 필수 (미설정 시 서버 시작 실패)
SESSION_SECRET_KEY=change-me-to-a-long-random-string
```

| 변수 | 필수 | 설명 |
|---|---|---|
| `ENV` | 선택 | `development`(기본) / `production` |
| `DATABASE_URL` | 선택 | SQLAlchemy 접속 URL. 미지정 시 `DB_*` 값으로 생성 |
| `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_CHARSET` | 조건부 | MySQL 접속 정보 |
| `OPENAI_API_KEY` | AI 기능 사용 시 | OpenAI API 키 |
| `OPENAI_MODEL` | 선택 | 기본값 `gpt-4o-mini` |
| `SESSION_SECRET_KEY` | 운영 필수 | 세션 쿠키 서명 키 |

### 3. 데이터베이스 준비

앱은 시작 시 테이블을 자동 생성하지 않습니다. [app/models.py](app/models.py)에 정의된 스키마에 맞게 MySQL 테이블을 미리 준비해야 합니다.

| 테이블 | 용도 |
|---|---|
| `users` | 사용자 계정 (`role`: `user` / `admin`) |
| `upload_files` | 업로드 파일 이력 |
| `upload_analysis_summaries` | 업로드별 AI 분석 요약 |
| `raw_inventory` | 업로드된 재고 원본 데이터 |
| `analysis_results` | 품목별 분석 결과 및 AI 진단 캐시 |
| `inventory_daily_metrics` | 일별 판매 지표(더미) |
| `inventory_monthly_sales` | 월별 판매 합계 |
| `strategy_actions` | 전략 조치 기록 |
| `customer_inquiries` | 고객 문의 및 관리자 답변 |

관리자 기능을 사용하려면 해당 사용자의 `users.role`을 `admin`으로 변경합니다.

### 4. 서버 실행

```powershell
uvicorn app.main:app --reload
```

브라우저에서 `http://localhost:8000` 접속 시 메인 페이지([static/mainpage.html](static/mainpage.html))가 표시됩니다.

---

## 🔒 보안 사항

- 비밀번호는 해시로 저장하며, 세션은 `itsdangerous`로 서명된 **HttpOnly / SameSite=Lax** 쿠키(유효기간 7일)를 사용합니다.
- `ENV=production`에서는 `Secure` 쿠키가 적용되고 `SESSION_SECRET_KEY`가 없으면 서버가 시작되지 않습니다. 운영 환경은 반드시 HTTPS로 배포하세요.
- 관리자 API는 `role=admin` 사용자만 접근할 수 있습니다.
- 업로드는 요청 크기, 실제 파일 크기(10MB), 파일 시그니처(XLSX), CSV 인코딩, 행 수(50,000)를 검증합니다.
- `/api/*` 응답에는 `Cache-Control: no-store`를 적용해 계정 전환 시 이전 사용자 데이터가 캐시에서 노출되지 않도록 합니다.
- LLM 호출은 사용자당 1건, 전체 동시 8건으로 제한되며 타임아웃과 응답 스키마 검증을 거칩니다.
- CORS 허용 출처는 [app/config.py](app/config.py)의 `CORS_ORIGINS`에서 관리합니다. 배포 시 실제 도메인으로 수정하세요.
- `.env` 파일과 DB 접속 정보, API 키는 저장소에 커밋하지 마세요.

---

## ⚠️ 제한 사항

- 일별 판매 지표와 모의 시세는 실제 데이터가 아닌 **더미 데이터**입니다. 실제 판매 이력을 반영하려면 별도의 판매 데이터 입력 경로가 필요합니다.
- DB 스키마 마이그레이션 도구가 포함되어 있지 않아 모델 변경 시 DB 스키마를 수동으로 반영해야 합니다.