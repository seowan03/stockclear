# JavaScript 및 CSS 폴더 안내

## 폴더 구조

- `js/`: 공통 및 페이지별 JavaScript 원본입니다. FastAPI가 `/js` URL로 제공합니다.
- `css/`: CSS 원본입니다. FastAPI가 `/css` URL로 제공합니다.
- `static/`: HTML 페이지와 정적 미디어를 둡니다. JS/CSS 파일은 이 폴더에 두지 않습니다.

## JavaScript 파일

| 파일 | 역할 |
| --- | --- |
| `js/session-header.js` | 로그인 상태, 사용자 이름, 로그아웃, 로그인 후 복귀 주소 처리 |
| `js/site-navigation.js` | 상단 메뉴 표시, 현재 페이지 강조, `upload_id` 전달 |
| `js/dashboard.js` | 대시보드 API 데이터 및 차트 처리 |
| `js/stockclear.js` | 재고 등급 분류, 색상 클래스, 숫자 포맷 등 공통 기능 |

기존 `static/js/`에 있던 헤더·메뉴 복사본은 제거했습니다. `static/` HTML은 `/js/...` 경로로 최상위 파일을 사용합니다.

## CSS 파일

| 파일 | 역할 |
| --- | --- |
| `css/base.css` | 전체 사이트 공통 기본 스타일. 기존 `static/style.css` |
| `css/style.css` | 사이트 공통 오버라이드 및 페이지별 스타일. `base.css`를 import |
| `css/sellpage.css` | 판매 페이지 전용 스타일. 기존 `static/sellpage/sellpage.css` |

기존 `static/css/style.css`는 `css/style.css`로, `static/style.css`는 `css/base.css`로 이동해 기존 적용 순서를 유지합니다. `static/sellpage/sellpage.css`도 `css/sellpage.css`로 이동했습니다.

## 경로 및 실행

`app/main.py`는 최상위 `js/`를 `/js`, 최상위 `css/`를 `/css`에 연결합니다. HTML은 `/js/...`와 `/css/...` 절대 경로를 사용합니다. 따라서 앱은 FastAPI로 실행해야 하며, HTML을 `file://`로 직접 열면 이 경로와 API가 정상 동작하지 않습니다.

메인페이지에서는 세션 헤더 스크립트를 중복 로드하지 않도록 참조를 하나로 정리했습니다.
