"""Repair old imports with substring-based dong assignment and merge crawl copies."""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from restaurant_identity import exemplary_source, find_address_dong, normalize_name, road_address_key

DATABASE = Path(__file__).resolve().parent / "restaurants.db"


def main():
    parser = argparse.ArgumentParser(description="주소 기반 동네 오분류와 원본 간 중복을 정리합니다.")
    parser.add_argument("--apply", action="store_true", help="정리 내용을 DB에 저장합니다. 생략하면 미리보기만 합니다.")
    args = parser.parse_args()

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = DATABASE.with_name(f"restaurants.backup-before-repair-{stamp}.db")
        shutil.copy2(DATABASE, backup)
        print(f"복구용 백업: {backup.name}")

    with sqlite3.connect(DATABASE, timeout=30) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            "SELECT id, neighborhood, name, address, category, source_url "
            "FROM restaurants ORDER BY id"
        )]
        others_by_identity = {}
        for row in rows:
            if exemplary_source(row["source_url"]):
                continue
            road_key = road_address_key(row["address"])
            if road_key:
                identity = (normalize_name(row["name"]), road_key)
                others_by_identity.setdefault(identity, []).append(row)

        merged = reclassified = unclassified = 0
        db.execute("BEGIN")
        for row in rows:
            exact_dong = find_address_dong(row["address"])
            if exact_dong and exact_dong != row["neighborhood"]:
                if args.apply:
                    db.execute("UPDATE restaurants SET neighborhood=? WHERE id=?", (exact_dong, row["id"]))
                reclassified += 1

        for row in rows:
            if not exemplary_source(row["source_url"]):
                continue
            road_key = road_address_key(row["address"])
            identity = (normalize_name(row["name"]), road_key) if road_key else None
            candidates = others_by_identity.get(identity, []) if identity else []
            if candidates:
                for candidate in candidates:
                    exact_dong = find_address_dong(candidate["address"])
                    if args.apply:
                        db.execute(
                            "UPDATE restaurants SET "
                            "neighborhood=COALESCE(NULLIF(?,''),neighborhood), "
                            "category=CASE WHEN ? <> '' THEN ? ELSE category END, source_url=? WHERE id=?",
                            (exact_dong, row["category"] or "", row["category"] or "", row["source_url"], candidate["id"]),
                        )
                if args.apply:
                    db.execute("DELETE FROM restaurants WHERE id=?", (row["id"],))
                merged += 1
                continue

            # Old crawler runs treated the street name 능동로 as the dong 능동.
            # If the page has no exact dong and no CSV match, keep the record in
            # the DB but hide it from the four-dong archive as unclassified.
            if not exact_dong:
                if args.apply:
                    db.execute("UPDATE restaurants SET neighborhood='미분류' WHERE id=?", (row["id"],))
                unclassified += 1

        if args.apply:
            db.commit()
        else:
            db.rollback()

    action = "정리 완료" if args.apply else "미리보기"
    print(f"{action}: 원본 중복 {merged}개 병합, 명확한 동 주소로 재분류 {reclassified}행, 동네 미확인 {unclassified}개")
    if not args.apply:
        print("적용하려면 py repair_restaurants.py --apply 를 실행하세요.")


if __name__ == "__main__":
    main()
