"""
과거 주문 데이터를 한 번에 소급해서 가져오는 백필(backfill) 스크립트.
평소 30분마다 자동 실행되는 fetch_cafe24.py와 달리, 이 스크립트는
과거 데이터를 처음 한 번 채워 넣을 때만 수동으로 실행한다.

fetch_cafe24.py와 같은 폴더(scripts/)에 있어야 하며, 그 안의 함수들을 그대로 재사용한다.

환경변수:
  CAFE24_CLIENT_ID / CAFE24_CLIENT_SECRET / CAFE24_REFRESH_TOKEN / CAFE24_MALL_ID
    -> fetch_cafe24.py와 동일 (GitHub Secrets에서 주입)
  BACKFILL_START_DATE (선택, 기본값 2026-01-01)
    -> 이 날짜부터 오늘까지 전체 주문을 소급 조회한다.
"""

import os
import datetime

from fetch_cafe24 import (
    refresh_access_token,
    fetch_orders,
    build_salesreport,
    build_channel_breakdown,
    build_product_breakdown,
    build_refund_stats,
    load_existing,
    save,
    write_new_refresh_token,
)

START_DATE = os.environ.get("BACKFILL_START_DATE", "2026-01-01")

# 카페24 주문 조회 API는 한 번 요청에 조회 가능한 날짜 범위에 제한이 있어,
# 90일 단위로 잘라서 여러 번 나눠 요청한다.
CHUNK_DAYS = 90


def daterange_chunks(start_date_str, end_date):
    start = datetime.date.fromisoformat(start_date_str)
    while start <= end_date:
        chunk_end = min(start + datetime.timedelta(days=CHUNK_DAYS - 1), end_date)
        yield start.isoformat(), chunk_end.isoformat()
        start = chunk_end + datetime.timedelta(days=1)


def main():
    access_token, new_refresh_token = refresh_access_token()
    write_new_refresh_token(new_refresh_token)

    today = datetime.date.today()
    store = load_existing()

    total_fetched = 0
    for start_date, end_date in daterange_chunks(START_DATE, today):
        print(f"조회 중: {start_date} ~ {end_date}")
        orders = fetch_orders(access_token, start_date, end_date)
        for order in orders:
            store["orders"][order["order_id"]] = order
        total_fetched += len(orders)
        print(f"  -> {len(orders)}건 (누적 반영 {total_fetched}건)")

    store["salesreport"] = build_salesreport(store["orders"])
    store["channel_breakdown"] = build_channel_breakdown(store["orders"])
    store["product_breakdown"] = build_product_breakdown(store["orders"])
    store["refund_stats"] = build_refund_stats(store["orders"])
    store["last_synced_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    save(store)

    print(
        f"백필 완료: {START_DATE} ~ {today.isoformat()} 기간 총 {total_fetched}건 조회, "
        f"저장소 누적 주문 {len(store['orders'])}건"
    )


if __name__ == "__main__":
    main()
