"""
카페24 Open API에서 주문/매출통계 데이터를 가져와 저장소에 JSON으로 누적 저장하는 스크립트.
GitHub Actions에서 주기적으로 실행되는 것을 전제로 작성됨.

필요한 환경변수 (GitHub Secrets에서 주입):
  CAFE24_CLIENT_ID
  CAFE24_CLIENT_SECRET
  CAFE24_REFRESH_TOKEN
  CAFE24_MALL_ID
"""

import os
import json
import base64
import datetime
import urllib.request
import urllib.parse

CLIENT_ID = os.environ["CAFE24_CLIENT_ID"]
CLIENT_SECRET = os.environ["CAFE24_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["CAFE24_REFRESH_TOKEN"]
MALL_ID = os.environ["CAFE24_MALL_ID"]

TOKEN_URL = f"https://{MALL_ID}.cafe24api.com/api/v2/oauth/token"
API_BASE = f"https://{MALL_ID}.cafe24api.com/api/v2/admin"

# 최근 며칠치를 매번 다시 덮어써서 취소/변경 반영 (매출 확정 전 주문 변동 대응)
LOOKBACK_DAYS = 7

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "cafe24-orders.json")


def refresh_access_token():
    """refresh_token으로 새 access_token(및 새 refresh_token)을 발급받는다."""
    pair = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth = base64.b64encode(pair.encode()).decode()
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        }
    ).encode()

    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as res:
        data = json.loads(res.read().decode())

    return data["access_token"], data["refresh_token"]


def api_get(access_token, path, params):
    query = urllib.parse.urlencode(params)
    url = f"{API_BASE}/{path}?{query}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode())


def fetch_orders(access_token, start_date, end_date):
    """기간 내 전체 주문을 페이지네이션으로 모두 수집한다."""
    orders = []
    offset = 0
    limit = 100
    while True:
        data = api_get(
            access_token,
            "orders",
            {
                "start_date": start_date,
                "end_date": end_date,
                "date_type": "order_date",
                "limit": limit,
                "offset": offset,
                "embed": "items",
            },
        )
        batch = data.get("orders", [])
        orders.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return orders


def fetch_salesreport(access_token, start_date, end_date):
    data = api_get(
        access_token,
        "reports/salesvolumebydate",
        {"start_date": start_date, "end_date": end_date},
    )
    return data.get("salesvolumebydate", [])


def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"orders": {}, "salesreport": {}, "last_synced_at": None}


def save(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def main():
    access_token, new_refresh_token = refresh_access_token()

    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    end_date = today.isoformat()

    orders = fetch_orders(access_token, start_date, end_date)
    salesreport = fetch_salesreport(access_token, start_date, end_date)

    store = load_existing()

    # 주문번호 기준으로 최신 상태를 덮어씀 (취소/변경 반영)
    for order in orders:
        store["orders"][order["order_id"]] = order

    # 날짜 기준으로 매출통계를 덮어씀
    for row in salesreport:
        store["salesreport"][row["date"]] = row

    store["last_synced_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    save(store)

    # 다음 스텝(Secret 갱신)에서 쓸 수 있도록 새 refresh_token을 출력
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"new_refresh_token={new_refresh_token}\n")

    print(
        f"동기화 완료: 주문 {len(orders)}건, "
        f"매출통계 {len(salesreport)}일치 (기간 {start_date} ~ {end_date})"
    )


if __name__ == "__main__":
    main()
