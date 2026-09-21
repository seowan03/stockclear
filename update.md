# LLM 오류 수정 내역

## 수정 파일

### `app/llm.py`

이번 수정은 `dev` 브랜치 리뷰에서 확인된 LLM 관련 오류를 대상으로 했습니다.

#### 1. OpenAI JSON 응답 형식 확인 및 표준화

OpenAI 요청의 `response_format`을 SDK가 요구하는 JSON object 형식인 `{"type": "json_object"}`로 유지·정리했습니다. 이를 통해 모델이 JSON 형식으로 응답하도록 요청합니다.

#### 2. OpenAI 클라이언트 지연 생성

기존에는 모듈을 import할 때 OpenAI 클라이언트를 생성했습니다. API 키가 없는 개발·테스트 환경에서는 LLM 기능을 사용하지 않아도 import 단계에서 오류가 발생할 수 있었습니다.

현재는 실제 AI 분석을 요청하는 시점에 API 키를 확인하고 클라이언트를 생성하도록 변경했습니다. API 키가 없으면 서버 전체가 중단되지 않고 안전한 분석 오류 응답을 반환합니다.

#### 3. 요청 timeout과 재시도 설정

OpenAI 클라이언트에 20초 timeout과 1회 재시도를 적용했습니다. 외부 API가 응답하지 않을 때 요청이 무한정 대기하는 것을 방지합니다.

#### 4. AI 응답 스키마 검증

`AIStrategy` Pydantic 모델을 추가해 다음 응답 형식을 검증합니다.

- `status`: 문자열
- `recommended_discount`: 0 이상 100 이하 숫자
- `comment`: 문자열

빈 응답, 잘못된 JSON, 필수 필드 누락, 할인율 범위 오류는 정상 응답으로 처리하지 않고 fallback으로 전환합니다.

#### 5. 내부 예외 메시지 비공개

기존에는 예외 원문을 그대로 `comment`에 포함했습니다. 현재는 상세 오류를 서버 로그에 기록하고, 사용자에게는 다음과 같은 일반화된 메시지만 반환합니다.

- AI 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.
- AI 분석 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.

API 키, 외부 API 응답, 내부 라이브러리 정보가 사용자 응답에 노출되지 않습니다.

#### 6. 기존 함수명 호환 유지

기존 코드에서 사용하던 오탈자 함수명 `get_ai_startegy`가 갑자기 깨지지 않도록 호환 별칭은 유지했습니다. 새 코드에서는 올바른 함수명인 `get_ai_strategy`를 사용해야 합니다.

## 검증 결과

- `python -m py_compile app/llm.py` 통과
- `OPENAI_API_KEY`가 없는 환경에서 모듈 import 성공
- API 키 누락 시 fallback 응답 반환 확인
- fallback 응답에 `OPENAI_API_KEY`와 내부 예외 원문이 포함되지 않음 확인

실제 OpenAI 응답 검증은 유효한 API 키와 네트워크 연결이 필요하므로 이번 검증에서는 수행하지 않았습니다.

-------------------

# H-6 LLM 원문 예외 노출 수정

## 수정 파일

### `app/llm.py`

- 기존 예외 처리에서 `str(e)`를 사용자 응답의 `comment`에 포함하던 동작을 제거했습니다.
- JSON 파싱 오류, Pydantic 응답 검증 오류, API 키 설정 오류는 서버 로그에만 기록합니다.
- OpenAI 호출 자체의 예외도 내부 로그에 기록하고, 사용자에게는 내부 구현 정보가 없는 일반 메시지만 반환합니다.
- AI 응답에 `status`, `recommended_discount`, `comment`가 모두 있는지 Pydantic 모델로 검증합니다.
- 할인율은 0 이상 100 이하인지 검증합니다.
- 빈 응답이나 잘못된 JSON 응답도 안전한 fallback 결과로 처리합니다.

## 수정 이유

예외 원문에는 API 설정, 외부 서비스 응답, 라이브러리 내부 정보가 포함될 수 있습니다. 이를 그대로 API 응답으로 반환하면 민감정보와 시스템 구조가 노출될 수 있으므로, 상세 오류는 서버 로그에만 남기고 클라이언트에는 일반화된 메시지를 반환하도록 변경했습니다.

## 검증 결과

- `python -m py_compile app/llm.py` 통과
- API 키가 없는 환경에서 함수가 예외를 외부로 전파하지 않고 fallback 응답을 반환하는 것을 확인
- fallback 응답에 `OPENAI_API_KEY`와 원본 예외 문자열이 포함되지 않는 것을 확인

---------------------

# 변경 범위 전체 공개

이번 작업에서 실제 프로젝트 코드로 수정된 파일은 `app/llm.py` 하나입니다. 다른 Python 파일, 라우터, 데이터베이스 모델, 프런트엔드 파일은 수정하지 않았습니다.

## 적용된 변경 사항

1. H-5 JSON 응답 옵션을 `{"type": "json_object"}` 형식으로 적용했습니다.
2. OpenAI 클라이언트를 모듈 import 시점이 아니라 AI 호출 시점에 생성하도록 변경했습니다.
3. `OPENAI_API_KEY`가 없는 경우 내부 오류를 기록하고 안전한 fallback 응답을 반환하도록 했습니다.
4. OpenAI 요청에 20초 timeout과 1회 재시도를 설정했습니다.
5. `AIStrategy` Pydantic 모델을 추가해 `status`, `recommended_discount`, `comment`를 검증하도록 했습니다.
6. `recommended_discount` 값이 0 이상 100 이하인지 검증하도록 했습니다.
7. 빈 응답과 잘못된 JSON 응답을 fallback으로 처리하도록 했습니다.
8. H-6에 따라 예외 원문을 사용자 응답에서 제거했습니다.
9. JSON 파싱 오류, 응답 검증 오류, 설정 오류, OpenAI 호출 오류는 서버 로그에만 기록하도록 했습니다.
10. 사용자에게는 내부 정보가 포함되지 않은 일반화된 오류 메시지만 반환하도록 했습니다.
11. 기존 오탈자 함수명 `get_ai_startegy`와의 호환 별칭은 유지했습니다.

## 수정하지 않은 사항

- `app/main.py`
- `app/router.py`
- `app/models.py`
- `app/database.py`
- `app/analysis.py`
- `requirements.txt`
- 프런트엔드 파일
- 환경변수 파일

## Git 상태

- `app/llm.py`의 코드 변경은 `3719542 json변경` 커밋에 포함되어 있습니다.
- `update.md`, `a.md`, `q.md`는 현재 별도 문서 파일이며 아직 Git에 추가되지 않은 상태입니다.
