import numpy as np
import pandas as pd

# 재고량/원가/판매가/판매량은 논리적으로 음수가 될 수 없는 값
NON_NEGATIVE_COLUMNS = ["재고량", "원가", "판매가", "판매량"]


def analyze_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """
    Excel에서 가져온 재고 데이터를 분석한다.

    필수 컬럼:
    상품명, 재고량, 원가, 입고일, 판매가, 판매량

    계산 컬럼:
    보관기간, 재고금액, 판매속도, 예상소진기간, 감가율, 위험점수, 위험등급
    """

    # --------------------------------
    # 1. 입고일을 날짜 형식으로 변환
    # --------------------------------
    df["입고일"] = pd.to_datetime(
        df["입고일"],
        errors="coerce"
    )

    # 날짜 변환에 실패한 데이터 확인
    if df["입고일"].isnull().any():
        raise ValueError(
            "입고일 데이터에 잘못된 날짜가 있습니다."
        )

    # --------------------------------
    # 1-1. 음수 값 검증
    # --------------------------------
    for column in NON_NEGATIVE_COLUMNS:
        if (df[column] < 0).any():
            raise ValueError(f"{column} 컬럼에 음수 값이 있습니다.")

    # --------------------------------
    # 2. 현재 날짜
    # --------------------------------
    today = pd.Timestamp.today().normalize()

    # --------------------------------
    # 3. 보관기간 계산
    # --------------------------------
    # 현재 날짜 - 입고일
    df["보관기간"] = (
        today - df["입고일"]
    ).dt.days

    # --------------------------------
    # 4. 재고금액 계산
    # --------------------------------
    # 재고량 × 원가
    df["재고금액"] = (
        df["재고량"] * df["원가"]
    )

    # --------------------------------
    # 5. 판매속도 계산 (벡터화 연산)
    # --------------------------------
    # 판매량 ÷ 보관기간, 보관기간이 0 이하이면 0으로 처리
    df["판매속도"] = np.where(
        df["보관기간"] > 0,
        df["판매량"] / df["보관기간"],
        0
    )

    # --------------------------------
    # 6. 예상 소진 기간 계산 (벡터화 연산)
    # --------------------------------
    # 현재 재고량 ÷ 하루 평균 판매량, 판매속도가 0이면 소진 불가로 간주해 9999로 처리
    df["예상소진기간"] = np.where(
        df["판매속도"] > 0,
        df["재고량"] / df["판매속도"],
        9999
    )

    # --------------------------------
    # 7. 감가율 계산 (벡터화 연산)
    # --------------------------------
    # (원가 - 판매가) ÷ 원가 × 100
    df["감가율"] = np.where(
        df["원가"] > 0,
        (df["원가"] - df["판매가"]) / df["원가"] * 100,
        0
    )

    # --------------------------------
    # 8. 위험점수 / 위험등급 판정
    # --------------------------------
    df["위험점수"], df["위험등급"] = _classify_risk(df)

    # --------------------------------
    # 9. API에서 사용할 수 있도록
    #    컬럼명을 영어로 변환
    # --------------------------------
    df = df.rename(columns={
        "상품명": "product_name",
        "재고량": "stock_qty",
        "원가": "purchase_price",
        "입고일": "received_date",
        "판매가": "selling_price",
        "판매량": "sales_qty",

        "보관기간": "storage_days",
        "재고금액": "inventory_value",
        "판매속도": "sales_speed",
        "예상소진기간": "days_to_sell",
        "감가율": "depreciation_rate",
        "위험점수": "final_score",
        "위험등급": "risk_grade",
    })

    return df


def _classify_risk(df: pd.DataFrame):
    """보관기간·예상소진기간·감가율을 0~100점 위험점수로 환산해 4단계 등급을 매긴다."""
    aging_score = (df["보관기간"] / 90 * 40).clip(upper=40)
    turnover_score = (df["예상소진기간"] / 180 * 30).clip(upper=30)
    depreciation_score = (df["감가율"] / 50 * 30).clip(lower=0, upper=30)

    final_score = (aging_score + turnover_score + depreciation_score).clip(lower=0, upper=100)

    grade = np.select(
        [final_score >= 70, final_score >= 45, final_score >= 25],
        ["처분 권장", "위험", "주의"],
        default="정상",
    )

    return final_score, grade