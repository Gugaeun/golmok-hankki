"""Scrape Gwangjin-gu's public exemplary-restaurant list into SQLite.

This intentionally crawls only the public list pages (not Naver Maps or review
pages), with a small delay between requests. The Seoul license CSV remains the
base inventory; this scraper adds the district's official exemplary label.
"""

import argparse
import re
import sqlite3
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app import DATABASE, app, init_db
from restaurant_identity import NEIGHBORHOODS, find_address_dong, normalize_name, road_address_key

BASE_URL = "https://www.gwangjin.go.kr"
LIST_URL = f"{BASE_URL}/health/bbs/B0000064/list.do"
MENU_NO = "300236"
SOURCE_LABEL = "광진구청 보건소 모범음식점 목록"


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def field_value(text, label, next_labels):
    next_group = "|".join(re.escape(item) for item in next_labels)
    match = re.search(
        rf"{re.escape(label)}\s*[:：]?\s*(.*?)(?=\s*(?:{next_group})\s*[:：]|$)",
        text,
        flags=re.IGNORECASE,
    )
    return clean_text(match.group(1)) if match else ""


def listing_links(soup):
    """Return one (title, URL, visible row text) tuple per detail link."""
    found = {}
    for anchor in soup.select('a[href*="/bbs/B0000064/view.do"]'):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        absolute_url = urljoin(BASE_URL, href)
        title = clean_text(anchor.get_text(" ", strip=True))
        row = anchor.find_parent("tr") or anchor.find_parent("li") or anchor.find_parent("article")
        row_text = clean_text(row.get_text(" ", strip=True)) if row else ""
        found[absolute_url] = (title, absolute_url, row_text)
    return list(found.values())


def fetch(session, url):
    response = session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return BeautifulSoup(response.text, "html.parser")


def parse_listing(title, url, row_text, session, delay):
    text = row_text
    category = field_value(text, "업태", ("주소", "전화번호"))
    address = field_value(text, "주소", ("전화번호", "약도보기"))

    # Some versions of the board show only the title in a row. Open that
    # restaurant's public detail page only when address/category is missing.
    if not address or not category:
        time.sleep(delay)
        detail = fetch(session, url)
        detail_text = clean_text(detail.get_text(" ", strip=True))
        category = category or field_value(detail_text, "업태", ("주소", "전화번호"))
        address = address or field_value(detail_text, "주소", ("전화번호", "약도보기"))
        if not title:
            for heading in detail.select("h1, h2, h3"):
                candidate = clean_text(heading.get_text(" ", strip=True))
                if candidate and "모범음식점" not in candidate:
                    title = candidate
                    break

    title = clean_text(title)
    address = clean_text(address)
    neighborhood = find_address_dong(address)
    if not title or not address or (neighborhood and neighborhood not in NEIGHBORHOODS):
        return None
    return {
        "name": title,
        "category": category,
        "address": address,
        "neighborhood": neighborhood,
        "source_url": url,
    }


def main():
    parser = argparse.ArgumentParser(
        description="광진구청 모범음식점 목록을 크롤링해 SQLite에 저장합니다."
    )
    parser.add_argument("--pages", type=int, default=13, help="목록 페이지 수 (기본: 13)")
    parser.add_argument("--delay", type=float, default=0.6, help="페이지 요청 간격 초 (기본: 0.6)")
    args = parser.parse_args()
    if args.pages < 1 or args.delay < 0:
        parser.error("--pages는 1 이상, --delay는 0 이상이어야 합니다.")

    with app.app_context():
        init_db()
    with sqlite3.connect(DATABASE, timeout=20) as db:
        cursor = db.execute("INSERT INTO crawl_runs (status) VALUES ('running')")
        run_id = cursor.lastrowid
        db.commit()

    session = requests.Session()
    session.headers.update({
        "User-Agent": "local-eats-portfolio/1.0 (public listing crawler)",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    })
    scraped = {}
    pages_visited = listings_seen = 0
    try:
        for page in range(1, args.pages + 1):
            if page > 1:
                time.sleep(args.delay)
            url = f"{LIST_URL}?menuNo={MENU_NO}&pageIndex={page}"
            soup = fetch(session, url)
            links = listing_links(soup)
            if not links:
                if page == 1:
                    raise RuntimeError(
                        "목록에서 상세 링크를 찾지 못했습니다. 광진구청 페이지 구조가 바뀌었는지 확인해 주세요."
                    )
                break
            pages_visited += 1
            listings_seen += len(links)
            for title, detail_url, row_text in links:
                item = parse_listing(title, detail_url, row_text, session, args.delay)
                if item:
                    scraped[(item["name"], item["address"])] = item
            print(f"목록 {page}페이지 확인: 링크 {len(links)}개, 대상 동네 누적 {len(scraped)}곳")
    except Exception as error:
        with sqlite3.connect(DATABASE, timeout=20) as db:
            db.execute(
                "UPDATE crawl_runs SET status='failed', finished_at=CURRENT_TIMESTAMP, "
                "pages_visited=?, listings_seen=?, target_found=?, error=? WHERE id=?",
                (pages_visited, listings_seen, len(scraped), str(error)[:500], run_id),
            )
        raise

    # Resolve official entries with abbreviated addresses from matching CSV
    # records. This avoids treating the street name "능동로" as the dong 능동.
    with sqlite3.connect(DATABASE, timeout=20) as db:
        db.row_factory = sqlite3.Row
        existing_rows = [dict(row) for row in db.execute(
            "SELECT id, neighborhood, name, address, category, source_url FROM restaurants"
        )]
    existing_by_name = {}
    for row in existing_rows:
        existing_by_name.setdefault(normalize_name(row["name"]), []).append(row)
    resolved = {}
    for key, item in scraped.items():
        name_key = normalize_name(item["name"])
        road_key = road_address_key(item["address"])
        matches = [
            row for row in existing_by_name.get(name_key, [])
            if road_key and road_address_key(row["address"]) == road_key
        ]
        neighborhood = item["neighborhood"]
        if not neighborhood:
            matched_areas = {
                find_address_dong(row["address"]) or row["neighborhood"]
                for row in matches
            } & set(NEIGHBORHOODS)
            if len(matched_areas) == 1:
                neighborhood = matched_areas.pop()
        if neighborhood not in NEIGHBORHOODS:
            continue
        item["neighborhood"] = neighborhood
        item["matches"] = matches
        resolved[key] = item
    scraped = resolved

    inserted = updated = 0
    with app.app_context():
        init_db()
        db = sqlite3.connect(DATABASE, timeout=20)
        try:
            for item in scraped.values():
                if item["matches"]:
                    for match in item["matches"]:
                        match_area = find_address_dong(match["address"]) or item["neighborhood"]
                        db.execute(
                            "UPDATE restaurants SET neighborhood=?, "
                            "category=CASE WHEN ? <> '' THEN ? ELSE category END, source_url=? WHERE id=?",
                            (match_area, item["category"], item["category"], item["source_url"], match["id"]),
                        )
                    updated += 1
                    continue
                db.execute(
                    "INSERT INTO restaurants "
                    "(neighborhood, name, category, address, source_url) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(name, address) DO UPDATE SET "
                    "category = CASE WHEN excluded.category <> '' THEN excluded.category "
                    "ELSE restaurants.category END, source_url = excluded.source_url",
                    (item["neighborhood"], item["name"], item["category"], item["address"], item["source_url"]),
                )
                inserted += 1
            db.commit()
        finally:
            db.close()

    with sqlite3.connect(DATABASE, timeout=20) as db:
        db.execute(
            "UPDATE crawl_runs SET status='success', finished_at=CURRENT_TIMESTAMP, "
            "pages_visited=?, listings_seen=?, target_found=?, inserted=?, updated=? WHERE id=?",
            (pages_visited, listings_seen, len(scraped), inserted, updated, run_id),
        )

    print(f"크롤링 저장 완료: 신규 {inserted}곳, 기존 자료 갱신 {updated}곳")
    print(f"출처: {SOURCE_LABEL} ({LIST_URL}?menuNo={MENU_NO})")
    print("대상 동네: 중곡동·군자동·화양동·능동")
    print("이 목록은 광진구청 지정 모범음식점이며, 전체 음식점이나 이용자 평점을 뜻하지 않습니다.")


if __name__ == "__main__":
    main()
