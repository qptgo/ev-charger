import streamlit as st
import requests
import math

# API 키 고정 완료
KAKAO_API_KEY = "0291962fedf3b68a740109ab85832466"
PUBLIC_DATA_KEY = "6a6056072358948fb6fdef29d501b7d1321dcc299215a20418dcb7c478f98614"

REGION_MAP = {
    "울산": "31", "부산": "26", "경남": "48", "경북": "47", 
    "대구": "27", "서울": "11", "경기": "41"
}

TARGET_OPERATORS = {
    "이브이시스": {"완속": 229.0, "급속": 298.0, "초급속": 345.0},
    "기후에너지환경부": {"완속": 295.0, "급속": 348.4, "초급속": 393.1},
    "한국전력": {"완속": 295.0, "급속": 348.4, "초급속": 393.1},
    "SK일렉링크": {"완속": 280.0, "급속": 330.0, "초급속": 345.0},
    "워터": {"완속": 270.0, "급속": 330.0, "초급속": 350.0},
    "차지비": {"완속": 269.0, "급속": 325.0, "초급속": 325.0},
}

TESLA_SUPERCHARGER_PRICE = 339.0
TESLA_SUPERCHARGER_KW = 250

def match_operator(busi_id, busi_nm):
    nm = busi_nm.upper()
    if any(k in nm for k in ["이브이시스", "EVSIS", "중앙제어", "롯데"]) or busi_id in ["JA", "LD"]:
        return "이브이시스"
    if any(k in nm for k in ["환경부", "환경공단"]) or busi_id == "ME":
        return "기후에너지환경부"
    if "한국전력" in nm or busi_id == "KP":
        return "한국전력"
    if any(k in nm for k in ["SK", "에스케이", "일렉링크"]) or busi_id == "SK":
        return "SK일렉링크"
    if any(k in nm for k in ["워터", "WATER", "브라이트에너지"]):
        return "워터"
    if "차지비" in nm or busi_id in ["GS", "PI"]:
        return "차지비"
    return None

def get_coords(place_name):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    res = requests.get(url, headers=headers, params={"query": place_name}).json()
    if not res.get("documents"):
        return None, None
    doc = res["documents"][0]
    return float(doc["y"]), float(doc["x"])

def get_route_coords(start_lat, start_lon, end_lat, end_lon):
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    params = {"origin": f"{start_lon},{start_lat}", "destination": f"{end_lon},{end_lat}"}
    res = requests.get(url, headers=headers, params=params).json()
    route_coords = []
    for section in res["routes"][0]["sections"]:
        for road in section["roads"]:
            v = road["vertexes"]
            for i in range(0, len(v), 10):
                route_coords.append((v[i+1], v[i]))
    return route_coords

@st.cache_data(ttl=600)
def get_chargers(zcode):
    url = "http://apis.data.go.kr/B552584/EvCharger/getChargerInfo"
    items = []
    for page in range(1, 3):
        params = {
            "serviceKey": PUBLIC_DATA_KEY,
            "pageNo": str(page),
            "numOfRows": "9999",
            "zcode": zcode,
            "dataType": "JSON"
        }
        res = requests.get(url, params=params)
        try:
            batch = res.json().get("items", {}).get("item", [])
            if not batch:
                break
            items.extend(batch)
        except Exception:
            break
    return items

def get_tesla_superchargers(route_coords, max_dist):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    superchargers = {}
    step = max(1, len(route_coords) // 10)
    for r_lat, r_lon in route_coords[::step]:
        params = {
            "query": "테슬라 수퍼차저",
            "x": str(r_lon),
            "y": str(r_lat),
            "radius": int(max_dist * 1000)
        }
        res = requests.get(url, headers=headers, params=params).json()
        for doc in res.get("documents", []):
            place_name = doc["place_name"]
            if "수퍼차저" in place_name or "슈퍼차저" in place_name:
                c_lat, c_lon = float(doc["y"]), float(doc["x"])
                if any(haversine(rlat, rlon, c_lat, c_lon) <= max_dist for rlat, rlon in route_coords):
                    superchargers[doc["id"]] = {
                        "name": place_name,
                        "operator": "테슬라 슈퍼차저",
                        "addr": doc.get("road_address_name") or doc.get("address_name"),
                        "kw": TESLA_SUPERCHARGER_KW,
                        "price": TESLA_SUPERCHARGER_PRICE,
                        "price_str": f"{TESLA_SUPERCHARGER_PRICE}원/kWh (현장변동)"
                    }
    return superchargers

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- 스마트폰 웹 화면 구성 ---
st.set_page_config(page_title="경로 최저가 충전소", page_icon="⚡")
st.subheader("⚡ 가는 길 최저가 충전소 찾기")

col1, col2 = st.columns(2)
with col1:
    start_place = st.text_input("출발지", value="대공원한신더휴")
with col2:
    end_place = st.text_input("목적지", value="솔봉숯불구이")

selected_regions = st.multiselect(
    "거쳐가는 지역 선택",
    options=list(REGION_MAP.keys()),
    default=["울산", "부산"]
)
max_dist = st.slider("경로 이탈 허용 거리 (km)", 0.5, 5.0, 2.0, 0.5)

if st.button("최저가 충전소 검색하기", type="primary", use_container_width=True):
    s_lat, s_lon = get_coords(start_place)
    e_lat, e_lon = get_coords(end_place)
    
    if not s_lat or not e_lat:
        st.error("출발지나 목적지 위치를 찾을 수 없습니다. 지역명을 포함해 다시 입력해 보세요.")
    else:
        with st.spinner("내비게이션 경로 및 충전소 요금 비교 중..."):
            route = get_route_coords(s_lat, s_lon, e_lat, e_lon)
            all_chargers = []
            for r_name in selected_regions:
                all_chargers.extend(get_chargers(REGION_MAP[r_name]))

            categorized = {"초급속(200kW+)": {}, "급속(50~100kW)": {}, "완속": {}}

            for ch in all_chargers:
                std_operator = match_operator(ch.get("busiId", ""), ch.get("busiNm", ""))
                if not std_operator:
                    continue
                try:
                    c_lat, c_lon = float(ch["lat"]), float(ch["lng"])
                except (ValueError, TypeError):
                    continue
                if ch.get("stat") != "2" or ch.get("limitYn") == "Y":
                    continue
                if not any(haversine(r_lat, r_lon, c_lat, c_lon) <= max_dist for r_lat, r_lon in route):
                    continue

                out_str = str(ch.get("output", "0")).strip()
                kw = int(out_str) if out_str.isdigit() else 7
                if kw < 50:
                    s_type, p_key = "완속", "완속"
                elif kw < 200:
                    s_type, p_key = "급속(50~100kW)", "급속"
                else:
                    s_type, p_key = "초급속(200kW+)", "초급속"

                price = TARGET_OPERATORS[std_operator][p_key]
                stat_id = ch["statId"]
                if stat_id not in categorized[s_type] or kw > categorized[s_type][stat_id]["kw"]:
                    categorized[s_type][stat_id] = {
                        "name": ch["statNm"],
                        "operator": std_operator,
                        "addr": ch["addr"],
                        "kw": kw,
                        "price": price,
                        "price_str": f"{price}원/kWh"
                    }

            tesla_stations = get_tesla_superchargers(route, max_dist)
            for t_id, t_info in tesla_stations.items():
                categorized["초급속(200kW+)"][f"TESLA_{t_id}"] = t_info

        for s_type, stations in categorized.items():
            st.markdown(f"### ■ {s_type}")
            sorted_list = sorted(stations.values(), key=lambda x: (x["price"], -x["kw"]))[:5]
            if not sorted_list:
                st.info("조건에 맞는 충전소가 없습니다.")
            for idx, st_info in enumerate(sorted_list, 1):
                st.markdown(
                    f"**{idx}위. {st_info['name']}** ({st_info['operator']})  \n"
                    f"💰 **{st_info['price_str']}** | ⚡ {st_info['kw']}kW  \n"
                    f"📍 {st_info['addr']}"
                )
            st.divider()
