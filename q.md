# 유비콘과 Live Server 대시보드 색상 차이 분석

## 확인한 사실

- 현재 `static/dashboard.html`의 `<body>`는 `bg-gray-100 text-gray-800` 클래스를 사용한다. 이 클래스는 Tailwind의 밝은 회색 배경을 적용한다.
- 다크 대시보드 규칙은 `static/style.css`의 `body.dashboard-page` 및 `.dashboard-page ...` 선택자에 정의되어 있다.
- 현재 대시보드 `<body>`에는 `dashboard-page` 클래스가 없다. 따라서 이 다크 규칙은 적용되지 않는다.
- `static/css/style.css`는 `../style.css`를 가져오므로, 두 CSS 파일은 대시보드에서 함께 로드된다.
- FastAPI 유비콘 앱은 `app/main.py`에서 `app.mount("/", StaticFiles(directory="static"), name="static")`로 `static/`을 루트 URL에 마운트한다. 따라서 유비콘 URL은 `http://127.0.0.1:8000/dashboard.html`이다.
- Five Server 화면의 URL은 `http://127.0.0.1:5500/static/dashboard.html`이다. Five Server는 작업 폴더를 루트로 제공하므로 `static/` 경로가 URL에 포함된다.
- 점검 시점에 `5500` 포트만 수신 중이었고 `8000` 포트에는 유비콘 프로세스가 없었다. 따라서 당시 유비콘이 어떤 파일을 제공했는지는 직접 비교할 수 없었다.

## 결론

같은 최신 `static/dashboard.html`을 제공한다면 유비콘과 Five Server가 색상을 다르게 만들지 않는다. 현재 소스 기준으로는 두 서버 모두 밝은 대시보드가 나오는 것이 정상이다.

유비콘에서만 이전의 어두운 파란색 화면이 보였다면 가장 가능성 높은 원인은 다음 둘 중 하나다.

1. 유비콘이 다른 작업 디렉터리 또는 이전 실행본의 `static/dashboard.html`을 제공했다.
2. `127.0.0.1:8000`과 `127.0.0.1:5500`은 서로 다른 origin이므로, 각 포트에 이전 HTML/CSS 캐시가 따로 남아 있었다.

## 일관되게 다크 테마를 적용하는 방법

대시보드 body를 다음처럼 바꾸면 기존 다크 대시보드 CSS가 적용된다.

```html
<body class="dashboard-page bg-[#0b1120] text-gray-100 min-h-screen flex flex-col antialiased selection:bg-blue-500 selection:text-white">
```

`bg-gray-100 text-gray-800`은 제거해야 한다. 이 변경 후 유비콘과 Five Server 모두 같은 파일을 제공하면 같은 다크 테마를 사용한다.

## 재현 및 점검 절차

1. 프로젝트 루트 `c:\pj\stockclear`에서 유비콘을 실행한다.

```powershell
uvicorn app.main:app --reload
```

2. 유비콘은 `http://127.0.0.1:8000/dashboard.html`로, Five Server는 `http://127.0.0.1:5500/static/dashboard.html`로 각각 연다.
3. 두 페이지에서 개발자 도구 Network 탭으로 `dashboard.html`과 `css/style.css`의 응답 내용을 비교한다.
4. 브라우저 강력 새로고침(`Ctrl+F5`) 후 다시 비교한다.
5. 서버 실행 위치가 프로젝트 루트인지 확인한다. 다른 위치에서 실행하면 유비콘이 다른 `static/` 디렉터리를 제공할 수 있다.