"""Import Gwangjin-gu restaurant CSV data into the local SQLite database."""

import argparse
import csv
import sqlite3
from pathlib import Path

from pyproj import Transformer

from app import DATABASE, app, init_db
from restaurant_identity import NEIGHBORHOODS, find_address_dong

SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-18656/S/1/datasetView.do"
FIELD_ALIASES = {
    "name": ("사업장명", "업소명", "업소명칭"),
    "category": ("업태구분명", "업종구분명", "업종"),
    "road_address": ("도로명전체주소", "도로명주소", "도로명주소전체"),
    "lot_address": ("소재지전체주소", "지번주소", "소재지주소"),
    "status": ("영업상태명", "상세영업상태명", "영업상태"),
    "x": ("대표좌표(X)", "좌표정보(X)", "X좌표"),
    "y": ("대표좌표(Y)", "좌표정보(Y)", "Y좌표"),
}


def find_field(row, aliases):
    normalized = {str(key).strip().lstrip("\ufeff"): value for key, value in row.items() if key}
    for name in aliases:
        if name in normalized and normalized[name] is not None:
            value = str(normalized[name]).strip()
            if value:
                return value
    return ""


def read_rows(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                reader = csv.DictReader(file)
                if not reader.fieldnames:
                    raise ValueError("CSV 헤더 행을 찾지 못했어요.")
                yield from reader
            return
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError(f"CSV 문자 인코딩을 읽지 못했어요: {last_error}")


def main():
    parser = argparse.ArgumentParser(description="광진구 일반음식점 CSV를 SQLite에 가져옵니다.")
    parser.add_argument("csv_file", help="다운로드한 광진구 일반음식점 CSV 파일 경로")
    args = parser.parse_args()
    csv_path = Path(args.csv_file).expanduser().resolve()
    if not csv_path.is_file():
        parser.error(f"파일을 찾을 수 없습니다: {csv_path}")

    imported = skipped = outside_area = 0
    # The Seoul Open Data page documents these CSV coordinates as EPSG:5174.
    transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
    with app.app_context():
        init_db()
    with sqlite3.connect(DATABASE) as db:
        for row in read_rows(csv_path):
            name = find_field(row, FIELD_ALIASES["name"])
            road = find_field(row, FIELD_ALIASES["road_address"])
            lot = find_field(row, FIELD_ALIASES["lot_address"])
            address = road or lot
            category = find_field(row, FIELD_ALIASES["category"])
            status = find_field(row, FIELD_ALIASES["status"])
            combined = f"{road} {lot}"
            longitude = latitude = None
            try:
                x = float(find_field(row, FIELD_ALIASES["x"]))
                y = float(find_field(row, FIELD_ALIASES["y"]))
                longitude, latitude = transformer.transform(x, y)
            except (TypeError, ValueError):
                pass

            if not name or not address:
                skipped += 1
                continue
            neighborhood = find_address_dong(combined)
            if neighborhood not in NEIGHBORHOODS:
                outside_area += 1
                continue
            db.execute(
                "INSERT INTO restaurants "
                "(neighborhood, name, category, business_status, address, longitude, latitude, source_url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(name, address) DO UPDATE SET "
                "business_status = COALESCE(NULLIF(excluded.business_status, ''), restaurants.business_status), "
                "longitude = COALESCE(restaurants.longitude, excluded.longitude), "
                "latitude = COALESCE(restaurants.latitude, excluded.latitude)",
                (neighborhood, name, category, status or None, address, longitude, latitude, SOURCE_URL),
            )
            imported += 1

    print(f"가져오기 완료: 중곡동·군자동·화양동·능동 {imported}행 반영, 제외 {skipped}행, 다른 동네 {outside_area}행")
    print("출처: 서울 열린데이터광장 - 서울시 광진구 일반음식점 인허가 정보")
    print("좌표가 있는 행은 EPSG:5174에서 위도·경도로 변환했습니다.")
    print("참고: 이 자료는 인허가 현황이며, 맛집 평가 자료는 아닙니다.")


if __name__ == "__main__":
    main()
