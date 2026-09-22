# StockClear 기술 스택 및 구조 분석

## 1. 프로젝트 개요

StockClear는 사용자가 업로드한 Excel/CSV 재고 데이터를 분석하여 보관 기간, 판매 속도, 예상 소진 기간, 재고 금액, 감가율을 계산하고 재고 위험등급을 제공하는 웹 애플리케이션이다. 분석 결과는 MySQL에 저장되며, 대시보드·재고 목록·전략·이력·내보내기 화면에서 조회할 수 있도록 API로 제공된다. 별도의 프론트엔드 프레임워크 없이 FastAPI 서버가 정적 HTML/CSS/JavaScript 파일과 REST 형태의 API를 함께 제공한다.

전체 처리 흐름은 다음과 같다.

```text
사용자
  -> HTML/CSS/JavaScript 화면
  -> FastAPI 업로드/인증 API
  -> Pandas + NumPy 데이터 검증 및 재고 지표 계산
  -> SQLAlchemy ORM을 통한 MySQL 저장
  -> 대시보드/재고/전략/이력 API 조회
  -> OpenAI GPT-4o-mini 기반 개별 재고 처방전
```

## 2. 기술 스택 요약

| 영역 | 기술 | 프로젝트 내 사용 상태 |
|---|---|---|
| 실행 언어 | Python | 백엔드, 데이터 분석, API 구현 |
| 백엔드 웹 프레임워크 | FastAPI | API, 인증, 파일 업로드, 정적 파일 제공 |
| ASGI 서버 | Uvicorn | FastAPI 실행 서버 |
| 프론트엔드 | HTML5, CSS3, 바닐라 JavaScript | 화면 구성과 사용자 상호작용 |
| CSS/UI | Tailwind CSS CDN, 자체 CSS | 화면 레이아웃과 스타일링 |
| 아이콘 | Font Awesome CDN | 화면 아이콘 |
| 차트 | Chart.js CDN | 대시보드 도넛 차트와 막대 차트 |
| 폰트 | Google Fonts의 Pretendard | 한국어 중심 UI 폰트 |
| 데이터 분석 | Pandas | Excel/CSV 파싱과 데이터프레임 계산 |
| 수치 계산 | NumPy | 벡터화 계산과 위험등급 분류 |
| 파일 처리 | openpyxl, python-multipart | XLSX 엔진과 multipart 파일 업로드 |
| 데이터베이스 | MySQL | 사용자, 원본 재고, 분석 결과, 업로드 이력 저장 |
| DB 드라이버 | PyMySQL | Python과 MySQL 연결 |
| ORM/DB 추상화 | SQLAlchemy | 모델 정의, 세션, 조회, 저장, 테이블 생성 |
| API 데이터 검증 | Pydantic | 요청 데이터와 LLM JSON 결과 검증 |
| LLM | OpenAI API, GPT-4o-mini | 상품별 재고 처분 전략 생성 |
| 외부 HTTP 통신 | Requests | 카카오 OAuth 토큰과 사용자 정보 API 호출 |
| 소셜 로그인 | Kakao OAuth 2.0 API | 카카오 계정 로그인 및 자동 회원가입 |
| 비밀번호 보안 | Werkzeug Security | 일반 회원 비밀번호 해시 생성/검증 |
| 세션 보안 | itsdangerous | 서명된 세션 쿠키 생성/검증 |
| 환경 설정 | python-dotenv, `.env` | DB·OAuth·OpenAI·세션 설정 로드 |
| 엑셀 다운로드 | SheetJS `xlsx` CDN | 브라우저에서 재고 목록을 Excel로 변환 |
| 개발 도구 | VS Code, Git, GitHub | 개발 및 버전 관리로 README에 기재됨 |

## 3. 기술별 상세 분석

### 3.1 Python

- **도입 이유**: 데이터 처리 라이브러리와 웹 API 프레임워크를 한 생태계에서 결합하기 쉽고, 재고 분석 로직을 빠르게 구현할 수 있기 때문이다.
- **주요 동작 및 역할**: `app/main.py`, `app/analysis.py`, `app/database.py`, `app/models.py`, `app/router.py`, `app/llm.py`, `app/security.py` 전반의 실행 언어다. 업로드 파일 처리, 분석, DB 저장, 인증, LLM 연동을 하나의 백엔드에서 수행한다.
- **담당 파트/역할**: 백엔드, 데이터 분석, 외부 서비스 연동.
- **제거 가능 여부**: **제거 불가에 가깝다.** Python을 제거하려면 백엔드와 분석 로직을 Node.js, Java, Go 등으로 전체 재작성해야 하며 FastAPI, Pandas, SQLAlchemy 등 관련 구성도 함께 교체해야 한다.

### 3.2 FastAPI

- **도입 이유**: Python 기반으로 REST API를 빠르게 만들 수 있고, 비동기 엔드포인트, 의존성 주입, 파일 업로드, Pydantic 연계가 기본 제공되기 때문이다.
- **주요 동작 및 역할**:
  - 회원가입, 로그인, 로그아웃, 현재 사용자 확인 API 제공.
  - `/api/upload`에서 `UploadFile`과 `File`로 Excel/CSV 업로드 처리.
  - `/api/dashboard`, `/api/inventory`, `/api/strategy`, `/api/history`, `/api/export` 등 조회 API 제공.
  - `Depends(get_db)`, `Depends(get_current_user)`로 DB 세션과 로그인 사용자를 주입.
  - `CORSMiddleware`로 허용된 개발 origin의 CORS 요청 처리.
  - `StaticFiles`와 `FileResponse`로 HTML, CSS, JavaScript 정적 파일 제공.
- **담당 파트/역할**: 백엔드 웹 프레임워크, API 서버.
- **제거 가능 여부**: **교체 가능하지만 사실상 핵심 기술이다.** Flask, Django, Express 등으로 대체할 수 있으나 모든 라우트, 의존성 주입, 업로드 처리, 미들웨어, 정적 파일 구성을 다시 작성해야 한다.

### 3.3 Uvicorn

- **도입 이유**: FastAPI 같은 ASGI 애플리케이션을 실행하기 위한 가볍고 표준적인 서버이기 때문이다.
- **주요 동작 및 역할**: `uvicorn app.main:app --reload`와 같은 방식으로 FastAPI 앱을 실행한다. 개발 환경에서는 `--reload`로 코드 변경 시 서버를 재시작할 수 있다.
- **담당 파트/역할**: 백엔드 실행 환경 및 애플리케이션 서버.
- **제거 가능 여부**: **대체 가능하다.** Hypercorn, Daphne, Gunicorn의 Uvicorn worker 등으로 바꿀 수 있다. 다만 FastAPI 앱을 실행할 ASGI 서버는 반드시 필요하다.

### 3.4 HTML5, CSS3, 바닐라 JavaScript

- **도입 이유**: 화면 수가 제한적이고 별도 빌드 도구 없이 빠르게 여러 페이지를 만들 수 있으며, FastAPI의 정적 파일 제공 방식과 직접 연결되기 때문이다.
- **주요 동작 및 역할**:
  - `static/` 아래에 로그인, 업로드, 대시보드, 재고, 전략, 이력, 내보내기 화면을 구성한다.
  - JavaScript의 `fetch`로 `/api/*` 백엔드 API를 호출하고 화면을 갱신한다.
  - `js/session-header.js`가 `/api/auth/me`를 확인해 로그인 상태와 로그아웃 UI를 갱신한다.
  - `js/stockclear.js`는 숫자 포맷, 위험 분류, 브라우저 저장 데이터 접근을 공통화한다.
- **담당 파트/역할**: 프론트엔드 화면, 사용자 입력, API 결과 표시.
- **제거 가능 여부**: **현재 형태로는 제거 불가하지만 교체 가능하다.** React, Vue, Svelte 등으로 바꿀 수 있으나 페이지 구성과 API 호출 코드를 재작성하고 프론트엔드 빌드/배포 체계를 추가해야 한다.

### 3.5 Tailwind CSS

- **도입 이유**: CDN으로 바로 사용할 수 있어 별도의 CSS 빌드 설정 없이 빠르게 반응형 레이아웃과 유틸리티 스타일을 적용할 수 있기 때문이다.
- **주요 동작 및 역할**: HTML의 클래스 조합으로 간격, 색상, 반응형 breakpoint, flex/grid, hover 상태 등을 지정한다. 여러 화면에서 `https://cdn.tailwindcss.com`을 로드한다.
- **담당 파트/역할**: 프론트엔드 스타일링/UI.
- **제거 가능 여부**: **가능하다.** 자체 CSS 또는 Bootstrap으로 대체할 수 있다. 제거 시 HTML의 Tailwind 유틸리티 클래스를 모두 일반 CSS 규칙으로 변환해야 하므로 화면 디자인이 크게 영향을 받는다.

### 3.6 자체 CSS

- **도입 이유**: Tailwind만으로 표현하기 어려운 공통 스타일과 화면별 효과를 관리하기 위해 사용한다.
- **주요 동작 및 역할**: `static/css/style.css`와 `static/style.css`에서 공통 폰트, 스크롤바, 입력 focus, 카드 hover, 페이지별 레이아웃과 색상을 정의한다.
- **담당 파트/역할**: 프론트엔드 프레젠테이션 계층.
- **제거 가능 여부**: **부분적으로 가능하다.** Tailwind 또는 다른 CSS 체계로 옮길 수 있으나 현재 CSS에 의존하는 페이지별 스타일과 상태 표현이 사라진다.

### 3.7 Font Awesome

- **도입 이유**: 업로드, 홈, 차트, 박스, 사용자 등 UI 아이콘을 직접 제작하지 않고 일관되게 사용할 수 있기 때문이다.
- **주요 동작 및 역할**: CDN에서 아이콘 폰트/CSS를 로드하고 `fa-solid`, `fa-cloud-arrow-up` 같은 클래스로 버튼과 내비게이션 아이콘을 표시한다.
- **담당 파트/역할**: 프론트엔드 UI 아이콘.
- **제거 가능 여부**: **가능하다.** SVG 아이콘, 다른 아이콘 라이브러리 또는 텍스트로 대체할 수 있다. 제거하면 아이콘이 표시되지 않으며 버튼의 시각적 이해도가 낮아질 수 있다.

### 3.8 Chart.js

- **도입 이유**: 대시보드에서 위험등급 분포와 상위 위험 재고를 짧은 코드로 시각화할 수 있기 때문이다.
- **주요 동작 및 역할**: `static/dashboard.html`에서 CDN으로 로드되고 `js/dashboard.js`에서 도넛 차트와 가로 막대 차트를 생성한다. 현재 대시보드 JavaScript는 `StockClear.getInventory()`로 브라우저 저장 데이터를 읽어 차트에 전달한다.
- **담당 파트/역할**: 프론트엔드 데이터 시각화.
- **제거 가능 여부**: **가능하다.** 표, CSS 막대 그래프, 다른 차트 라이브러리로 대체할 수 있다. 제거하면 대시보드 차트가 사라지고 위험 분포를 텍스트나 표로 제공해야 한다.

### 3.9 Pandas

- **도입 이유**: Excel/CSV를 데이터프레임으로 읽고 컬럼 검증 및 대량 행 계산을 간결하게 처리할 수 있기 때문이다.
- **주요 동작 및 역할**:
  - `pd.read_excel`로 XLSX/XLS를 읽고 `pd.read_csv`로 CSV를 읽는다.
  - 날짜를 변환하고 필수 컬럼과 빈 데이터 여부를 검증한다.
  - `analyze_inventory()`에서 보관 기간, 재고 금액, 판매 속도, 예상 소진 기간, 감가율, 위험점수를 계산한다.
  - 분석 결과를 DB 저장용 레코드와 API 응답용 dictionary로 변환한다.
- **담당 파트/역할**: 백엔드 데이터 분석 및 파일 처리.
- **제거 가능 여부**: **가능하지만 대체 작업이 크다.** Python 표준 `csv`와 `openpyxl`을 직접 조합하거나 Polars 등으로 대체할 수 있다. 데이터프레임 연산, 날짜 처리, 컬럼 변환을 다시 구현해야 하므로 업로드와 분석 로직 전반이 영향을 받는다.

### 3.10 NumPy

- **도입 이유**: Pandas 컬럼에 대한 벡터화 조건 계산을 빠르고 간결하게 수행하기 위해 사용한다.
- **주요 동작 및 역할**: `np.where`로 판매 속도, 예상 소진 기간, 감가율을 계산하고 `np.select`로 위험등급을 분류한다. 행마다 Python 함수를 호출하는 것보다 대량 데이터 처리에 유리하다.
- **담당 파트/역할**: 데이터 분석의 수치 계산 엔진.
- **제거 가능 여부**: **가능하다.** Pandas의 `where`, `select` 또는 순수 Python 조건문으로 대체할 수 있다. 다만 계산 코드가 복잡해지고 대량 업로드 성능이 저하될 수 있다.
- **구성상 참고**: `app/analysis.py`에서 직접 import하지만 현재 `requirements.txt`에는 `numpy`가 명시되어 있지 않다. Pandas 설치 과정의 간접 의존성으로 동작할 수 있으나 재현 가능한 설치를 위해 직접 추가하는 편이 안전하다.

### 3.11 openpyxl 및 python-multipart

- **도입 이유**: Excel 파일을 읽고 브라우저의 multipart/form-data 업로드를 처리하기 위해 사용한다.
- **주요 동작 및 역할**:
  - `openpyxl`: `pd.read_excel`이 XLSX 파일을 해석할 때 사용하는 Excel 엔진이다.
  - `python-multipart`: FastAPI의 `UploadFile`과 `File(...)`을 통한 multipart 파일 업로드 파싱을 지원한다.
  - 서버는 확장자뿐 아니라 XLSX/XLS 파일 signature와 CSV 인코딩(UTF-8-SIG, CP949)을 검사한다.
- **담당 파트/역할**: 백엔드 파일 입출력 및 업로드 처리.
- **제거 가능 여부**: **각각 조건부로 가능하다.** XLSX 지원을 제거하면 openpyxl을 뺄 수 있지만 Excel 업로드가 불가능해진다. multipart 업로드를 JSON 또는 별도 스토리지 방식으로 바꾸면 python-multipart를 뺄 수 있으나 현재 업로드 API 계약을 변경해야 한다.

### 3.12 MySQL, PyMySQL, SQLAlchemy

- **도입 이유**: 사용자별 재고와 분석 결과를 영속적으로 저장하고, 여러 API 화면에서 조건 검색·정렬·조회를 일관되게 처리하기 위해 관계형 DB와 ORM을 사용한다.
- **주요 동작 및 역할**:
  - **MySQL**: `users`, `raw_inventory`, `analysis_results`, `upload_files` 테이블에 사용자·원본 데이터·분석 결과·업로드 이력을 저장한다.
  - **PyMySQL**: SQLAlchemy가 MySQL에 연결할 때 사용하는 Python 드라이버다. 연결 URL은 `mysql+pymysql://...` 형식이다.
  - **SQLAlchemy**: `models.py`의 ORM 모델, `SessionLocal`, `get_db`, join/filter/order/group_by 쿼리, 테이블 자동 생성을 담당한다.
  - 애플리케이션 시작 시 `Base.metadata.create_all()`을 호출하고, 기존 `upload_files` 테이블의 누락 컬럼을 조건부 `ALTER TABLE`로 보완한다.
- **담당 파트/역할**: 데이터베이스, 영속성, ORM.
- **제거 가능 여부**: **MySQL은 다른 DB로 교체 가능하지만 DB 자체는 사실상 필요하다.** SQLite로 바꾸면 단일 서버 개발/소규모 운영은 쉬워질 수 있으나 동시성·운영 확장성·MySQL 호환 설정에 영향이 있다. SQLAlchemy를 제거하고 SQL을 직접 작성할 수 있지만 세션, 모델, 쿼리 코드를 대부분 다시 구현해야 한다. PyMySQL은 PostgreSQL 등 다른 DB 드라이버로 교체할 수 있다.

### 3.13 Pydantic

- **도입 이유**: API 입력값과 LLM 응답의 형식을 선언적으로 검증해 잘못된 데이터가 서비스 내부로 들어오는 것을 줄이기 위해 사용한다.
- **주요 동작 및 역할**:
  - `InventoryItem`이 `/api/ai-diagnose` 요청의 상품명, 재고량, 가격, 분석 지표 타입을 검증한다.
  - `SignupRequest`, `LoginRequest`가 회원가입·로그인 JSON body를 검증한다.
  - `AIStrategy`가 LLM 응답의 `status`, `recommended_discount(0~100)`, `comment`를 검증한다.
- **담당 파트/역할**: 백엔드 API 계약 및 데이터 검증.
- **제거 가능 여부**: **가능하지만 권장하지 않는다.** 수동 검증으로 바꿀 수 있으나 타입 변환, 오류 응답, LLM 응답 검증을 직접 구현해야 하며 잘못된 입력이 통과할 위험이 커진다.

### 3.14 OpenAI API와 GPT-4o-mini

- **도입 이유**: 규칙 기반 지표만 제공하는 것을 넘어 상품별 재고 상태에 맞춘 자연어 처분 전략과 할인율을 생성하기 위해 사용한다.
- **주요 동작 및 역할**:
  - `app/llm.py`가 `OPENAI_API_KEY`로 OpenAI 클라이언트를 만들고 `gpt-4o-mini`에 상품명, 보관 기간, 재고량, 원가를 전달한다.
  - JSON object 형식으로 `status`, `recommended_discount`, `comment`를 요청한다.
  - Pydantic으로 결과를 검증하며 빈 응답, JSON 오류, API 오류가 발생하면 분석 오류 결과를 반환한다.
  - `router.py`의 `/api/ai-diagnose`는 입력 크기 제한, 사용자/IP별 호출 횟수 제한, 12초 timeout을 적용하고 실패 시 규칙 기반 전략으로 fallback한다.
- **담당 파트/역할**: AI/LLM, 상품별 처분 전략 생성.
- **제거 가능 여부**: **가능하다.** OpenAI 호출을 제거하고 `router.py`의 `_rule_based_strategy()`만 사용하면 핵심 재고 분석은 유지된다. 대신 자연어 처방전의 유연성, 상품별 설명, AI 기반 할인 제안이 사라지고 고정 임계값 기반 결과만 제공된다. API 키 비용과 외부 네트워크 의존성은 줄어든다.

### 3.15 Requests 및 Kakao OAuth 2.0

- **도입 이유**: 직접 회원가입 외에 카카오 계정으로 로그인할 수 있도록 외부 OAuth 서버와 통신하기 위해 사용한다.
- **주요 동작 및 역할**:
  - `/api/auth/kakao`가 카카오 인증 페이지로 redirect한다.
  - callback에서 authorization code를 카카오 token endpoint에 보내 access token을 받고, 사용자 정보 API에서 이메일과 닉네임을 조회한다.
  - 신규 사용자라면 DB에 자동 가입시키고, 기존 세션 쿠키 발급 로직을 재사용해 대시보드로 이동시킨다.
  - `requests`가 토큰 교환과 사용자 정보 조회 HTTP 요청을 수행한다.
- **담당 파트/역할**: 백엔드 외부 인증 연동.
- **제거 가능 여부**: **가능하다.** 카카오 로그인 기능을 제거하면 일반 이메일/비밀번호 로그인만 남는다. `requests`는 카카오 연동을 다른 HTTP 클라이언트로 교체하거나 소셜 로그인을 제거하면 제거할 수 있다.

### 3.16 Werkzeug Security

- **도입 이유**: 비밀번호를 평문으로 저장하지 않고 검증된 해시 방식으로 보관하기 위해 사용한다.
- **주요 동작 및 역할**: 회원가입과 카카오 자동 가입 시 `generate_password_hash()`로 해시를 저장하고, 일반 로그인 시 `check_password_hash()`로 입력값을 검증한다.
- **담당 파트/역할**: 백엔드 인증 보안.
- **제거 가능 여부**: **가능하지만 동등한 비밀번호 해시 구현으로 대체해야 한다.** bcrypt, Argon2, Passlib 등으로 교체할 수 있다. 대체 없이 제거하면 비밀번호 평문 저장 또는 안전하지 않은 검증으로 이어질 수 있다.

### 3.17 itsdangerous

- **도입 이유**: 서버 측 세션 저장소 없이도 변조 여부와 만료 시간을 검증할 수 있는 서명 세션 쿠키가 필요하기 때문이다.
- **주요 동작 및 역할**: `URLSafeTimedSerializer`가 사용자 ID를 서명된 토큰으로 만들고, `max_age` 7일 조건으로 토큰을 검증한다. `HttpOnly`, `SameSite=Lax`, 운영 환경의 `Secure` 쿠키 옵션도 함께 적용한다.
- **담당 파트/역할**: 백엔드 세션 인증 및 보안.
- **제거 가능 여부**: **가능하지만 인증 방식 교체가 필요하다.** Redis/DB 세션, JWT, 프레임워크 기본 세션으로 바꿀 수 있다. 단순히 제거하면 로그인 상태를 안전하게 유지할 수 없다.

### 3.18 python-dotenv와 환경 변수

- **도입 이유**: DB 접속 정보, OpenAI API key, Kakao client secret, 세션 secret 같은 환경별 민감 설정을 코드와 분리하기 위해 사용한다.
- **주요 동작 및 역할**: `load_dotenv()`로 `.env` 값을 읽고 `DB_HOST`, `DATABASE_URL`, `OPENAI_API_KEY`, `KAKAO_CLIENT_ID`, `KAKAO_CLIENT_SECRET`, `SESSION_SECRET_KEY`, `ENV` 등에 주입한다.
- **담당 파트/역할**: 환경 설정 및 배포 구성.
- **제거 가능 여부**: **라이브러리는 가능하지만 환경 설정 방식은 필요하다.** 운영 환경 변수나 다른 설정 관리 도구를 직접 사용하면 python-dotenv를 제거할 수 있다. `.env` 로딩과 환경별 설정이 사라지면 실행 환경마다 설정을 별도로 주입해야 한다.

### 3.19 SheetJS `xlsx`

- **도입 이유**: 백엔드에서 별도 파일을 만들지 않고 브라우저에서 조회된 재고 데이터를 Excel 파일로 내려받기 위해 사용한다.
- **주요 동작 및 역할**: `export.html`과 `inventory.html`에서 CDN의 SheetJS를 로드하여 JSON/테이블 데이터를 워크시트로 변환하고 `.xlsx` 파일로 다운로드한다.
- **담당 파트/역할**: 프론트엔드 내보내기 기능.
- **제거 가능 여부**: **가능하다.** CSV 다운로드나 서버 측 Excel 생성으로 대체할 수 있다. 제거하면 XLSX 다운로드가 사라지며 CSV만 제공하거나 서버에 파일 생성 로직을 추가해야 한다.

### 3.20 브라우저 `localStorage`

- **도입 이유**: 프론트엔드에서 로그인 표시 이름과 일부 재고 데이터를 페이지 이동 사이에 유지하기 위해 사용한다.
- **주요 동작 및 역할**: `stockclear-account-name`으로 표시용 계정명을 캐시하고, `stockclearInventory`로 대시보드 공통 JavaScript가 재고 데이터를 읽는다.
- **담당 파트/역할**: 프론트엔드 상태/캐시.
- **제거 가능 여부**: **가능하다.** 모든 화면이 서버 API를 직접 조회하도록 통일할 수 있다. 다만 현재 `js/dashboard.js`와 `js/stockclear.js`가 브라우저 저장 데이터에 의존하는 부분은 API 기반으로 수정해야 하며, localStorage를 제거하면 새로고침 후 해당 캐시 데이터가 유지되지 않는다.
- **구조상 참고**: 백엔드에는 `/api/dashboard`와 `/api/inventory`가 존재하지만 일부 프론트 로직은 여전히 localStorage를 사용한다. 따라서 문서상 API 구조와 실제 화면 데이터 흐름 사이에 정리할 여지가 있다.

### 3.21 Git, GitHub, VS Code

- **도입 이유**: 소스 변경 이력 관리, 팀 협업, 코드 편집과 실행을 위해 사용한다.
- **주요 동작 및 역할**: README에는 Git/GitHub 협업 및 버전 관리, VS Code 개발 환경이 기재되어 있다. 애플리케이션 실행 시 직접 호출되는 런타임 기술은 아니다.
- **담당 파트/역할**: 개발 환경, 협업, 소스 코드 관리.
- **제거 가능 여부**: **애플리케이션에서는 제거 가능하다.** GitHub 대신 다른 Git 호스팅을 사용하거나 Git 없이 개발할 수 있지만, 팀 협업·변경 이력·코드 리뷰·복구 편의성이 크게 낮아진다. VS Code 역시 다른 IDE로 대체 가능하다.

## 4. 핵심 기능별 기술 조합

### 파일 업로드와 분석

1. 브라우저 HTML form이 `multipart/form-data`로 `.xlsx`, `.xls`, `.csv` 파일을 전송한다.
2. FastAPI의 `UploadFile`과 `python-multipart`가 파일을 받는다.
3. 서버가 파일 크기, 확장자, signature, CSV 인코딩, 최대 행 수와 필수 컬럼을 검사한다.
4. Pandas가 파일을 읽고 NumPy 기반 벡터 연산으로 분석 지표와 4단계 위험등급을 계산한다.
5. SQLAlchemy ORM을 통해 MySQL의 원본 재고와 분석 결과에 저장한다.

### 인증과 사용자별 데이터 보호

1. 일반 회원가입은 Werkzeug로 비밀번호를 해시해 저장한다.
2. 로그인 또는 카카오 OAuth 성공 후 itsdangerous 서명 세션 쿠키를 발급한다.
3. 보호된 API는 `get_current_user`에서 쿠키 서명과 만료 시간을 확인하고 DB 사용자 존재 여부를 검증한다.
4. DB 조회는 현재 사용자 ID로 필터링하여 다른 사용자의 재고·업로드 이력을 조회하지 않도록 한다.

### AI 처방전

1. 인증된 사용자가 상품별 지표를 `/api/ai-diagnose`로 보낸다.
2. Pydantic이 입력 구조를 검증하고, 크기 및 사용자/IP별 rate limit을 적용한다.
3. OpenAI GPT-4o-mini가 JSON 형식의 상태·할인율·설명을 반환한다.
4. Pydantic `AIStrategy`가 응답을 검증한다.
5. timeout이나 분석 오류가 발생하면 고정 임계값을 이용한 `_rule_based_strategy()` 결과를 반환한다.

## 5. 제거·교체 시 영향 요약

| 제거 대상 | 제거 후 유지되는 기능 | 직접적인 영향 |
|---|---|---|
| OpenAI API | 파일 업로드, 수치 분석, DB 저장, 대시보드 | AI 자연어 처방전과 동적 할인 추천이 사라지고 규칙 기반 결과만 남음 |
| Chart.js | 재고 조회와 분석 API | 차트 대신 표/텍스트 표시 필요 |
| Tailwind CSS | 백엔드와 데이터 처리 | 모든 UI 유틸리티 클래스를 CSS로 재작성해야 함 |
| Kakao OAuth/Requests | 일반 이메일 로그인 | 카카오 소셜 로그인 제거 |
| itsdangerous | 데이터 분석 자체 | 세션 저장소 또는 JWT 등 다른 인증 방식 필요 |
| MySQL | 분석 계산 로직 | 다른 DB로 데이터 이전 및 연결 설정 변경 필요 |
| SQLAlchemy | DB 자체 | SQL, 세션 수명, 모델 매핑, 쿼리 전부 직접 구현 필요 |
| Pandas/NumPy | 인증과 화면 | Excel/CSV 파싱 및 계산 로직을 다른 라이브러리나 직접 구현해야 함 |
| SheetJS | 조회 API | 브라우저 Excel 다운로드 제거 또는 서버 측 생성 필요 |
| localStorage | 서버 인증/DB | 프론트가 매번 API를 조회하도록 데이터 흐름 수정 필요 |

## 6. 현재 구조에서 확인되는 참고 사항

- `app/analysis.py`는 `numpy`를 직접 사용하지만 `requirements.txt`에 명시되어 있지 않다. 배포 재현성을 위해 `numpy`를 직접 의존성으로 관리하는 것이 좋다.
- 서버 업로드 제한은 코드상 파일 10MB, 요청 본문 약 11MB, 최대 50,000행이다. `static/upload.html`의 안내 문구에는 최대 50MB로 표시되어 있어 실제 제한과 UI 문구가 일치하지 않는다.
- `app/main.py`에는 `/api/dashboard`, `/api/inventory` 등 DB 기반 API가 있지만 `js/dashboard.js`와 `js/stockclear.js`의 일부 로직은 `localStorage`의 `stockclearInventory`를 읽는다. 장기적으로는 서버 API를 단일 데이터 원천으로 통일하는 것이 바람직하다.
- `app/router.py`의 AI 진단은 OpenAI 실패 시 규칙 기반 fallback을 제공하므로 OpenAI를 제거해도 핵심 수치 분석 서비스는 운영할 수 있다.
- CDN 기반 Tailwind, Font Awesome, Chart.js, Google Fonts, SheetJS는 네트워크나 CDN 장애 시 화면 일부 기능에 영향을 받을 수 있다. 운영 안정성이 중요하면 정적 번들 또는 자체 호스팅을 검토할 수 있다.
- DB 스키마 변경은 현재 `create_all()`과 수동 `ALTER TABLE` 보완 함수에 의존한다. 운영 규모가 커지면 Alembic 같은 migration 도구를 별도로 도입하는 편이 안전하다.

## 7. 결론

StockClear의 핵심 필수 구성은 **Python + FastAPI + Pandas/NumPy + SQLAlchemy + MySQL + HTML/CSS/JavaScript**다. 이 조합이 파일 업로드부터 분석, 저장, 조회까지의 기본 제품 기능을 담당한다. **OpenAI, Kakao OAuth, Chart.js, Tailwind, SheetJS**는 각각 AI 처방전, 소셜 로그인, 시각화, UI 스타일, Excel 다운로드를 강화하는 선택적 기능에 가깝다. 따라서 비용이나 운영 복잡도를 줄여야 한다면 OpenAI와 소셜 로그인을 먼저 선택적으로 제거할 수 있지만, 데이터 분석과 사용자별 결과 저장을 유지하려면 Pandas·DB·인증의 대체 설계를 함께 마련해야 한다.

## 8. `main.py` 파일 분리 추천안

### 8.1 현재 `main.py`의 문제점

현재 `app/main.py`는 애플리케이션 시작점인 동시에 다음 책임을 모두 가지고 있다.

1. FastAPI 앱 생성, CORS 설정, startup 처리, 정적 파일 mount
2. 카카오 OAuth 로그인과 callback 처리
3. 일반 회원가입·로그인·로그아웃·현재 사용자 확인
4. 업로드 파일 크기, 확장자, signature, CSV 인코딩 검증
5. Pandas 파일 파싱과 재고 분석 호출
6. 업로드 결과와 분석 결과의 DB 저장
7. 업로드 이력 조회·삭제
8. 대시보드·재고 목록·전략·내보내기 조회

이 구조에서는 한 기능을 수정할 때 관련 없는 import까지 함께 확인해야 하고, 라우트 간 의존성이 섞여 테스트하기 어렵다. 특히 라우트 함수 안에 파일 파싱과 DB 저장이 같이 있어 API 테스트, 분석 테스트, 저장 테스트를 독립적으로 작성하기 어렵다.

### 8.2 추천 디렉터리 구조

현재 파일을 한 번에 재작성하기보다, 기존 `models.py`, `schemas.py`, `security.py`, `analysis.py`, `database.py`를 유지하면서 아래 파일을 추가하는 방식을 추천한다.

```text
app/
├── main.py                  # FastAPI 앱 생성, 공통 middleware, router 등록, 정적 파일 mount
├── config.py                # 환경 변수와 업로드/서비스 설정
├── dependencies.py          # DB 세션, 현재 사용자 등 공통 의존성의 진입점
├── database.py              # SQLAlchemy engine, SessionLocal, Base, DB 초기화
├── models.py                # SQLAlchemy ORM 모델
├── schemas.py               # API 요청/응답 Pydantic 모델
├── security.py              # 세션 쿠키와 현재 사용자 인증
├── analysis.py              # 재고 지표 계산과 위험등급 분류
├── llm.py                   # OpenAI 호출과 AI 응답 검증
├── router.py                # 기존 AI 진단 router 또는 routers 패키지의 공통 진입점
├── routers/
│   ├── __init__.py
│   ├── auth.py              # 일반 회원가입/로그인/로그아웃/me
│   ├── kakao.py             # 카카오 OAuth 시작 및 callback
│   ├── upload.py            # 파일 업로드 API
│   ├── history.py           # 업로드 이력 조회/삭제 API
│   ├── inventory.py         # 대시보드/재고/전략/내보내기 API
│   └── ai.py                # AI 진단 API
├── services/
│   ├── __init__.py
│   ├── upload_service.py    # 파일 검증, Pandas 파싱, 중복 해시
│   ├── inventory_service.py # 분석 결과 및 원본 재고 DB 저장/조회
│   └── kakao_service.py     # 카카오 token/user 정보 요청 및 사용자 생성
└── utils/
   ├── __init__.py
   └── file_validation.py   # 크기, signature, 인코딩, 확장자 검증
```

`routers/`는 HTTP 요청과 응답에 집중하고, `services/`는 비즈니스 로직과 DB 작업을 담당하게 한다. 이렇게 나누면 URL 변경은 router에서, 분석·저장 정책 변경은 service에서 처리할 수 있다.

### 8.3 각 코드의 이동 위치

| 현재 `main.py` 책임 | 추천 파일 | 이동할 내용 |
|---|---|---|
| 환경 변수 로드와 상수 | `app/config.py` | `load_dotenv()`, `KAKAO_*`, 업로드 크기/행 수, CORS origin, 위험등급 메타 |
| 앱 생성과 공통 설정 | `app/main.py` | `FastAPI()`, `include_router()`, CORS middleware, startup, static mount |
| 카카오 로그인 | `app/routers/kakao.py` | `/api/auth/kakao`, `/api/auth/kakao/callback` 라우트 |
| 카카오 외부 통신/사용자 생성 | `app/services/kakao_service.py` | `requests.post/get`, 사용자 정보 해석, 신규 User 생성 |
| 일반 인증 API | `app/routers/auth.py` | `SignupRequest`, `LoginRequest`, signup/login/logout/me |
| 파일 검증 | `app/utils/file_validation.py` | `_check_upload_content_length`, `_read_upload_file_with_limit`, `_detect_csv_encoding`, `_validate_upload_file_signature` |
| 업로드 처리 API | `app/routers/upload.py` | `/api/upload` 라우트 함수와 HTTP 오류 변환 |
| 업로드 비즈니스 로직 | `app/services/upload_service.py` | Pandas 파일 읽기, 필수 컬럼 확인, content hash, `analyze_inventory()` 호출 |
| 분석 결과 저장 | `app/services/inventory_service.py` | `_save_analysis_results`, `_save_raw_inventory`, 업로드 batch 저장 정책 |
| 업로드 이력 API | `app/routers/history.py` | `/api/history` GET/DELETE 라우트 |
| 공통 분석 조회 | `app/services/inventory_service.py` | `_query_user_analysis` 및 사용자별 조회 함수 |
| 대시보드/재고/전략/내보내기 API | `app/routers/inventory.py` | `/api/dashboard`, `/api/inventory`, `/api/strategy`, `/api/export` |
| AI 진단 API | `app/routers/ai.py` 또는 기존 `app/router.py` | 현재 `router.py`의 `APIRouter`와 `/api/ai-diagnose` |
| DB와 모델 | 기존 파일 유지 | `database.py`, `models.py`, `schemas.py`, `security.py`, `analysis.py`, `llm.py` |

### 8.4 분리 후 `main.py`의 목표 형태

분리 작업이 끝나면 `main.py`는 아래 정도의 역할만 남기는 것이 좋다.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, ensure_upload_files_user_id_column
from app.routers import ai, auth, history, inventory, kakao, upload

app = FastAPI(title="StockClear Backend", version="1.0")

app.add_middleware(
   CORSMiddleware,
   allow_origins=[
      "http://localhost:3000",
      "http://localhost:5173",
      "http://127.0.0.1:3000",
      "http://127.0.0.1:5173",
   ],
   allow_credentials=True,
   allow_methods=["*"],
   allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(kakao.router)
app.include_router(upload.router)
app.include_router(history.router)
app.include_router(inventory.router)
app.include_router(ai.router)

@app.on_event("startup")
def on_startup():
   Base.metadata.create_all(bind=engine)
   ensure_upload_files_user_id_column()

app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/", StaticFiles(directory="static"), name="static")
```

실제 코드에서는 각 router에 `APIRouter(prefix="/api")` 또는 기존 경로를 그대로 지정해 현재 프론트엔드의 URL 계약을 유지해야 한다. 이 예시는 구조를 보여주기 위한 목표 형태이며, 모든 import와 router 정의를 그대로 복사해 실행하는 완성 코드가 아니다.

### 8.5 권장 작업 순서

1. **설정과 공통 상수 분리**
  - `config.py`를 만들고 환경 변수와 업로드 제한값을 옮긴다.
  - 기존 값과 기본값을 그대로 유지하여 동작 변화를 막는다.

2. **조회 API 분리**
  - 대시보드·재고·전략·내보내기 API를 `routers/inventory.py`로 옮긴다.
  - `_query_user_analysis`는 `inventory_service.py`로 옮긴다.
  - 조회 API는 상대적으로 부작용이 적어 첫 분리 대상으로 적합하다.

3. **업로드 검증과 저장 분리**
  - 파일 바이트 검증을 `utils/file_validation.py`로 옮긴다.
  - Pandas 파싱과 분석 호출을 `upload_service.py`로 옮긴다.
  - DB 저장 함수는 `inventory_service.py`로 옮긴다.
  - `/api/upload` router는 인증, service 호출, HTTP 응답 변환만 담당하게 한다.

4. **인증과 카카오 로그인 분리**
  - 일반 인증은 `routers/auth.py`, 카카오 로그인은 `routers/kakao.py`로 나눈다.
  - 카카오 HTTP 통신은 `kakao_service.py`로 옮겨 router가 외부 API 세부사항을 알지 않게 한다.

5. **AI router 정리**
  - 현재 `app/router.py`의 AI 진단 라우터를 `routers/ai.py`로 이동하거나, 파일명을 `ai.py`로 바꾼다.
  - 기존 `app.include_router(router)` 등록을 `app.include_router(ai.router)`로 변경한다.

6. **마지막으로 `main.py` 정리**
  - 사용하지 않는 import와 기존 함수 정의를 제거한다.
  - 앱 생성, middleware, startup, router 등록, static mount만 남긴다.

### 8.6 분리할 때 반드시 지켜야 할 점

- **API 경로 유지**: `/api/auth/*`, `/api/upload`, `/api/history`, `/api/dashboard`, `/api/inventory`, `/api/strategy`, `/api/export`, `/api/ai-diagnose`를 그대로 유지해야 현재 HTML/JavaScript가 계속 동작한다.
- **인증 의존성 유지**: 보호된 router에 `current_user: User = Depends(get_current_user)`를 그대로 적용해야 사용자 간 데이터가 섞이지 않는다.
- **DB 세션 수명 유지**: 각 라우트에서 `db: Session = Depends(get_db)`를 사용하고, service에 세션을 인자로 전달한다. service 안에서 별도의 전역 세션을 만들면 커넥션 누수와 트랜잭션 관리 문제가 생길 수 있다.
- **커밋 경계 확인**: 현재 업로드 처리에는 분석 결과 저장, 업로드 이력 저장, 원본 재고 저장이 여러 함수로 나뉘어 있다. 분리하면서 commit 순서를 바꾸면 실패 시 일부 데이터만 남을 수 있으므로 트랜잭션 정책을 함께 검토해야 한다.
- **순환 import 방지**: router가 `main.app`을 import하지 않게 하고, 설정·DB·보안·service 방향으로만 의존하게 한다. `main.py`는 router를 import하고 router는 `main.py`를 import하지 않는 단방향 구조가 적절하다.
- **설정 상수의 단일 출처 유지**: `RISK_GRADE_META`, 업로드 제한값, CORS origin을 여러 파일에 복사하지 말고 `config.py` 또는 별도 상수 모듈 하나에서 관리한다.
- **Pydantic schema 확장**: 현재 `SignupRequest`, `LoginRequest`는 `schemas.py`로 옮기고, 가능하면 업로드·대시보드·재고·내보내기 응답 모델도 추가해 router의 응답 형태를 명확히 한다.
- **외부 요청 timeout 추가 검토**: 카카오 `requests.post/get`은 별도 timeout이 없으므로 `kakao_service.py`로 옮길 때 timeout과 상태 코드 검사를 함께 넣는 것이 좋다.

### 8.7 분리 후 검증 방법

파일을 옮길 때마다 다음 순서로 검증하는 것을 추천한다.

1. `python -m compileall app`로 import 및 문법 오류 확인
2. `uvicorn app.main:app --reload`로 앱 기동 확인
3. `/`, `/api/auth/me` 등 공개 엔드포인트 확인
4. 회원가입·로그인 후 `/api/upload` 호출 확인
5. `/api/history`, `/api/dashboard`, `/api/inventory`, `/api/strategy`, `/api/export` 응답 확인
6. `/api/ai-diagnose`의 OpenAI 성공·timeout·fallback 동작 확인
7. 기존 프론트엔드 페이지에서 로그인, 업로드, 조회, 다운로드 흐름 확인

### 8.8 최종 추천

가장 현실적인 방법은 **router를 먼저 기능별로 분리하고, 복잡한 업로드·DB 저장 로직을 그 다음 service로 이동하는 단계적 리팩터링**이다. 처음부터 `main.py`를 완전히 새로 작성하면 import 경로, router 등록, DB commit 순서, 인증 의존성이 동시에 바뀌어 문제를 추적하기 어렵다. 기존 API 경로와 함수 동작을 유지한 채 파일 위치만 단계적으로 바꾸면 기능 회귀 위험을 낮추면서도 `main.py`를 애플리케이션 조립 파일로 축소할 수 있다.

### 8.9 적용 결과

위 추천안을 실제 코드에 적용하여 다음과 같이 분리했다.

- `app/main.py`: FastAPI 앱 생성, CORS, startup, router 등록, 정적 파일 제공만 담당
- `app/config.py`: 환경 변수, 업로드 제한, CORS origin, 위험등급 메타데이터 관리
- `app/routers/auth.py`: 일반 회원가입·로그인·로그아웃·현재 사용자 API
- `app/routers/kakao.py`: 카카오 OAuth 시작 및 callback API
- `app/routers/upload.py`: 업로드 HTTP 요청과 오류 응답 처리
- `app/routers/history.py`: 업로드 이력 조회·삭제 API
- `app/routers/inventory.py`: 대시보드·재고·전략·내보내기 API
- `app/routers/ai.py`: AI 진단 및 규칙 기반 fallback API
- `app/services/upload_service.py`: 파일 파싱, 필수 컬럼 검증, 중복 해시, 분석 호출
- `app/services/inventory_service.py`: 재고·분석 결과·업로드 이력 저장 및 공통 조회
- `app/services/kakao_service.py`: 카카오 token/user 정보 요청과 사용자 생성
- `app/utils/file_validation.py`: 파일 크기, signature, CSV 인코딩 검증
- 기존 AI 라우터와 중복되던 `app/router.py`는 새 `app/routers/ai.py`로 대체하여 제거

분리 후에도 기존 API 경로는 유지했다. `python -m compileall app` 검증과 FastAPI OpenAPI 경로 확인을 통과했으며, 기존 API 경로가 모두 등록되어 있음을 확인했다. 업로드 저장은 분리 과정에서 원본 재고와 분석 결과를 한 번씩 저장하도록 통합했다.