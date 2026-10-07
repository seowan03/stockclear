from decimal import Decimal, ROUND_CEILING

import numpy as np
import pandas as pd

# 재고량/원가/판매가/판매량은 논리적으로 음수가 될 수 없는 값
NON_NEGATIVE_COLUMNS = ["재고량", "원가", "판매가", "판매량"]


def calculate_safety_stock(
    max_daily_sales: float,
    average_daily_sales: float,
    max_lead_time_days: float = 5,
    average_lead_time_days: float = 2,
) -> int:
    values = tuple(Decimal(str(value)) for value in (
        max_daily_sales, average_daily_sales,
        max_lead_time_days, average_lead_time_days,
    ))
    if any(not value.is_finite() or value < 0 for value in values):
        raise ValueError("Sales and lead times must be finite and non-negative.")
    maximum_sales, average_sales, maximum_days, average_days = values
    if average_sales > maximum_sales or average_days > maximum_days:
        raise ValueError("Average values must not exceed maximum values.")
    safety_stock = maximum_sales * maximum_days - average_sales * average_days
    if safety_stock <= 0:
        safety_stock = average_sales * average_days
    return int(safety_stock.to_integral_value(rounding=ROUND_CEILING))


def calculate_date_based_days_to_sell(
    remaining_stock_qty: int | None,
    weekly_sales_qty: int | None,
    recorded_days: int,
    window_days: int = 7,
) -> int | None:
    if remaining_stock_qty is None or remaining_stock_qty < 0:
        return None
    if remaining_stock_qty == 0:
        return 0
    if window_days <= 0 or recorded_days < window_days or weekly_sales_qty is None or weekly_sales_qty <= 0:
        return None

    average_daily_sales = Decimal(weekly_sales_qty) / Decimal(recorded_days)
    return int((Decimal(remaining_stock_qty) / average_daily_sales).to_integral_value(rounding=ROUND_CEILING))


def analyze_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """
    Excel에서 가져온 재고 데이터를 분석한다.

    필수 컬럼:
    상품명, 재고량, 원가, 입고일, 판매가, 판매량

    계산 컬럼:
    보관기간, 재고금액, 판매속도, 예상소진기간, 감가율, 위험점수, 위험등급
    """

    df = df.copy()

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
    # 현재 날짜 - 입고일 (미래 날짜 입력 시 음수가 되지 않도록 clip 처리)
    # ---------- [수정: 보관기간 최소 0일 보장] ----------
    df["보관기간"] = (today - df["입고일"]).dt.days.clip(lower=0)
    # ---------------------------------------------------

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

    # ---------- [신규 추가: 4번 연산 결과 중 NaN / Inf 방어 처리] ----------
    numeric_result_cols = ["보관기간", "재고금액", "판매속도", "예상소진기간", "감가율", "위험점수"]
    for col in numeric_result_cols:
        # np.inf / -np.inf 및 NaN 수치 정제
        df[col] = df[col].replace([np.inf, -np.inf], np.nan).fillna(0)
    # ---------------------------------------------------------------------

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


def calculate_risk_score_components(storage_days, days_to_sell, depreciation_rate):
    """Return the component scores used by the stored inventory risk score."""
    aging_score = np.minimum(np.asarray(storage_days, dtype=float) / 90 * 40, 40)
    turnover_score = np.minimum(np.asarray(days_to_sell, dtype=float) / 180 * 30, 30)
    depreciation_score = np.clip(np.asarray(depreciation_rate, dtype=float) / 50 * 30, 0, 30)
    return {
        "storage_score": aging_score,
        "turnover_score": turnover_score,
        "depreciation_score": depreciation_score,
    }


def _classify_risk(df: pd.DataFrame):
    """보관기간·예상소진기간·감가율을 0~100점 위험점수로 환산해 4단계 등급을 매긴다."""
    components = calculate_risk_score_components(
        df["보관기간"],
        df["예상소진기간"],
        df["감가율"],
    )
    aging_score = components["storage_score"]
    turnover_score = components["turnover_score"]
    depreciation_score = components["depreciation_score"]

    final_score = np.clip(aging_score + turnover_score + depreciation_score, 0, 100)

    grade = np.select(
        [final_score >= 70, final_score >= 45, final_score >= 25],
        ["악성", "장기", "주의"],
        default="정상",
    )

    return final_score, grade