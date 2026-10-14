# 골목 한끼

중곡동·군자동·화양동·능동 맛집을 모아보는 Flask + SQLite 포트폴리오 프로젝트입니다.

## 실행

```powershell
cd work/local-eats
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
py app.py
```

처음 한 번은 프로젝트 폴더의 `.env` 파일을 열어 `NAVER_MAP_CLIENT_ID=` 뒤에 발급받은 Client ID를 입력하고 저장하세요. Geocoding을 사용할 때는 `NAVER_MAP_API_KEY_ID`와 `NAVER_MAP_API_KEY`도 입력합니다. `.env`는 Git에 포함되지 않으므로 키를 안전하게 보관할 수 있고, 이후에는 새 터미널을 열어도 다시 설정할 필요가 없습니다.

브라우저에서 `http://127.0.0.1:5000`을 여세요. 지도 인증은 Naver Cloud Platform에 등록한 `http://localhost`에서 실행해야 합니다.

첫 실행 시 `restaurants.db`가 만들어지고, 화면 구성 확인용 샘플 행 두 개가 들어갑니다. 샘플 주소와 좌표는 실제 가게 정보가 아니므로 실제 데이터로 바꿔야 합니다. Client Secret은 브라우저나 저장소에 넣지 마세요.

## 현재 포함된 기능

- SQLite에 맛집 데이터 저장
- 중곡동·군자동·화양동·능동·전체 필터
- 가게 이름, 음식 종류, 주소 검색
- 웹 폼에서 맛집을 SQLite에 직접 추가 (좌표와 출처 URL은 선택)
- Client ID가 설정된 경우 지도와 좌표 마커 표시
- 지도에는 현재 목록 페이지에 한정하지 않고, 선택한 동네·검색 조건에 맞는 좌표가 있는 업소를 전체 표시
- 가까이 겹친 마커를 숫자로 묶고, 확대하면 개별 가게 표시
- 같은 이름·같은 도로 건물번호로 여러 출처에 중복된 업소는 화면에서 한 번만 표시
- 지도 팝업과 카드에서 광진구청 모범음식점 출처 표시
- 광진구청 보건소 모범음식점 목록을 크롤링해 네 동네 자료를 SQLite에 추가/갱신
- 최근 성공한 크롤링 시간, 확인 건수, 대상·신규 건수를 화면에 표시
- 주소에서 행정동을 정확히 판별해 `능동로`를 `능동`으로 잘못 분류하지 않음

일반음식점 CSV 좌표는 지역 좌표계에서 WGS84 위도·경도로 바꿔 사용하며, 크롤링한 모범음식점에 한해 Naver Geocoding API로 좌표를 보완할 수 있습니다.

## 광진구 일반음식점 CSV 가져오기

1. [서울 열린데이터광장 데이터 페이지](https://data.seoul.go.kr/dataList/OA-18656/S/1/datasetView.do)를 엽니다.
2. 미리보기의 CSV 다운로드 기능으로 파일을 내려받습니다. 데이터 페이지의 Sheet 미리보기에는 최대 1,000건 제한이 있으므로, 전체 파일 다운로드 메뉴가 보이면 전체 파일을 선택하세요.
3. CMD에서 프로젝트 폴더로 이동한 뒤 다음처럼 실행합니다. CSV 파일을 CMD 창으로 끌어다 놓으면 파일 경로를 쉽게 입력할 수 있습니다.

```cmd
py import_restaurants.py "C:\Users\내이름\Downloads\다운로드한파일.csv"
```

스크립트는 중곡동·군자동·화양동·능동 주소를 골라 현재 SQLite DB에 반영하고, CSV의 영업상태명으로 폐업·휴업 이력을 기본 맛집 목록에서 제외합니다. CSV의 대표좌표(X/Y)는 EPSG:5174 좌표계에서 WGS84 위도·경도로 변환해 마커에 사용합니다. 데이터 제공처와 출처표시 조건은 위 데이터 페이지를 확인하세요.

기존 DB에서 옛 주소 분류 기준으로 가져온 자료를 한 번 정리하려면 `py repair_restaurants.py --apply`를 실행합니다. 실행 전에 복구용 DB 백업을 자동으로 만듭니다.

## CSV 좌표를 이용한 지도 마커

서울 열린데이터광장 CSV에는 대표좌표 X/Y가 들어 있습니다. `pyproj`가 설치된 뒤 CSV를 다시 가져오면 기존 행도 좌표가 채워집니다.

```cmd
pip install -r requirements.txt
py import_restaurants.py "%USERPROFILE%\Downloads\서울시 광진구 일반음식점 인허가 정보.csv"
```

이 데이터에서는 주소마다 Geocoding API를 호출하지 않습니다. Naver Maps Dynamic Map은 지도 렌더링에 사용합니다.

## 모범음식점 목록 크롤링

서울시 CSV는 일반음식점 인허가 목록이고, 아래 크롤러는 광진구청 보건소의 공개 모범음식점 HTML 목록을 읽습니다. 두 데이터는 이름과 주소로 중복을 합치며, 크롤러 출처 URL도 SQLite에 저장합니다. 목록에 올라온 업소만 모범음식점으로 표시할 수 있고, 이 자료가 전체 가게나 평점 정보를 제공하는 것은 아닙니다.

```cmd
pip install -r requirements.txt
py crawl_restaurants.py
```

기본 설정은 목록 최대 13페이지를 확인하고 페이지 요청 사이에 0.6초 쉽니다. 일부 페이지만 확인하려면 `py crawl_restaurants.py --pages 2`처럼 실행하세요. 실행 결과가 SQLite의 `crawl_runs` 이력표에 저장되고, 성공한 마지막 수집 정보가 웹 화면에 표시됩니다.

크롤링한 모범음식점만 지도 좌표가 필요하면 Naver Geocoding API로 해당 업소만 변환할 수 있습니다. API 키가 환경 변수로 설정된 CMD에서 실행하세요.

```cmd
py geocode_restaurants.py --exemplary-only
```

이 옵션은 좌표가 비어 있는 모범음식점만 최대 30곳 처리하므로 일반음식점 전체를 조회하지 않습니다.

출처: [광진구청 보건소 모범음식점 목록](https://www.gwangjin.go.kr/health/bbs/B0000064/list.do?menuNo=300236). 페이지 형식이나 접근 정책이 바뀌면 크롤러 선택자를 조정해야 합니다.
