"""Fill missing restaurant coordinates through the NAVER Maps Geocoding API."""

import argparse
import os
import sqlite3
import time

import requests

from app import DATABASE, app, init_db

GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"


def main():
    parser = argparse.ArgumentParser(description="주소가 있는 맛집을 위도·경도로 변환합니다.")
    parser.add_argument("--limit", type=int, default=30, help="이번 실행에서 처리할 최대 가게 수 (기본: 30)")
    parser.add_argument(
        "--exemplary-only",
        action="store_true",
        help="광진구청 모범음식점 크롤링 자료 중 좌표가 없는 가게만 처리합니다.",
    )
    args = parser.parse_args()
    key_id = os.getenv("NAVER_MAP_API_KEY_ID")
    key = os.getenv("NAVER_MAP_API_KEY")
    if not key_id or not key:
        parser.error("NAVER_MAP_API_KEY_ID와 NAVER_MAP_API_KEY 환경 변수를 먼저 설정해 주세요.")
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    with app.app_context():
        init_db()
    headers = {
        "x-ncp-apigw-api-key-id": key_id,
        "x-ncp-apigw-api-key": key,
        "Accept": "application/json",
    }
    updated = no_match = 0
    query = (
        "SELECT id, address FROM restaurants "
        "WHERE address IS NOT NULL AND TRIM(address) <> '' "
        "AND (longitude IS NULL OR latitude IS NULL)"
    )
    if args.exemplary_only:
        query += " AND source_url LIKE 'https://www.gwangjin.go.kr/health/bbs/B0000064/view.do%'"
    query += " ORDER BY id LIMIT ?"
    with sqlite3.connect(DATABASE, timeout=20) as db:
        rows = db.execute(query, (args.limit,)).fetchall()

    if args.exemplary_only:
        print(f"좌표 변환 대상: 크롤링한 모범음식점 {len(rows)}곳 (최대 {args.limit}곳)")
    else:
        print(f"좌표 변환 대상: 미좌표 가게 {len(rows)}곳 (최대 {args.limit}곳)")
    if not rows:
        print("처리할 가게가 없습니다.")
        return
    for restaurant_id, address in rows:
        try:
            response = requests.get(
                GEOCODE_URL,
                headers=headers,
                params={"query": address, "count": 1},
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as error:
            print(f"요청 실패 (ID {restaurant_id}): {error}")
            continue
        except ValueError:
            print(f"응답을 JSON으로 읽지 못했어요 (ID {restaurant_id}).")
            continue

        matches = result.get("addresses", [])
        if not matches:
            no_match += 1
            time.sleep(0.12)
            continue
        try:
            longitude = float(matches[0]["x"])
            latitude = float(matches[0]["y"])
        except (KeyError, TypeError, ValueError):
            no_match += 1
            time.sleep(0.12)
            continue
        # Keep the write transaction short so the Flask page can read the DB.
        with sqlite3.connect(DATABASE, timeout=20) as db:
            db.execute(
                "UPDATE restaurants SET longitude = ?, latitude = ? WHERE id = ?",
                (longitude, latitude, restaurant_id),
            )
        updated += 1
        time.sleep(0.12)

    print(f"좌표 변환 완료: {updated}곳, 주소 검색 결과 없음/형식 문제 {no_match}곳")
    print("지도에서 결과를 보려면 브라우저를 새로고침하세요.")


if __name__ == "__main__":
    main()
