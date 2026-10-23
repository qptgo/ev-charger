import streamlit as st
import requests
import math
import folium
from streamlit_folium import st_folium

# API 키 고정
KAKAO_API_KEY = "0291962fedf3b68a740109ab85832466"
PUBLIC_DATA_KEY = "6a6056072358948fb6fdef29d501b7d1321dcc299215a20418dcb7c478f98614"

REGION_NAME_TO_CODE = {
    "서울": "11", "부산": "26", "대구": "27", "인천": "28",
    "광주": "29", "대전": "30", "울산": "31", "세종": "36",
    "경기": "41", "강원": "42", "충북": "43", "충청북도": "43",
    "충남": "44", "충청남도": "44", "전북": "45", "전라북도": "45",
    "전남": "46", "전라남도": "46", "경북": "47", "경상북도": "47",
    "경남": "48", "경상남도": "48", "제주": "50"
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

def classify_charger_speed(kw):
    if 20 <= kw <= 30:
        return "완속(20~30kW)", "완속"
    elif 50 <= kw < 200:
        return "급속(50~100kW)", "급속"
    elif kw >= 200:
        return "초급속(200kW+)", "초급속"
    return None, None

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
    if not res.get("routes"):
        return route_coords
    for section in res["routes"][0]["sections"]:
        for road in section["roads"]:
            v = road["vertexes"]
            for i in range(0, len(v), 2):
                route_coords.append((v[i+1], v[i]))
    return route_coords

def get_walking_route(start_lat, start_lon, end_lat, end_lon):
    """보행자/산책로/자전거도로 우선 경로 탐색 (OSRM Foot API, 실패 시 카카오 연동)"""
    try:
        url = f"https://routing.openstreetmap.de/routed-foot/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
        res = requests.get(url, timeout=4).json()
        if res.get("code") == "Ok":
            coords = res["routes"][0]["geometry"]["coordinates"]
            dist_km = res["routes"][0]["distance"] / 1000.0
            return [(c[1], c[0]) for c in coords], dist_km
    except Exception:
        pass
    # 백업: 카카오 경로
    pts = get_route_coords(start_lat, start_lon, end_lat, end_lon)
    dist = sum(haversine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) for i in range(len(pts)-1)) if len(pts) > 1 else 0.0
    return pts, dist

def calculate_destination_point(lat, lon, distance_km, bearing_deg):
    """출발 좌표에서 특정 방향(각도)으로 일정 거리 떨어진 목표 좌표 계산"""
    R = 6371.0
    brng = math.radians(bearing_deg)
    d = distance_km
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1)*math.cos(d/R) + math.cos(lat1)*math.sin(d/R)*math.cos(brng))
    lon2 = lon1 + math.atan2(math.sin(brng)*math.sin(d/R)*math.cos(lat1), math.cos(d/R)-math.sin(lat1)*math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def detect_regions_from_route(route_coords):
    url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    detected_codes = set()
    detected_names = []
    step = max(1, len(route_coords) // 15)
    sample_points = route_coords[::step]
    if route_coords and route_coords[-1] not in sample_points:
        sample_points.append(route_coords[-1])
        
    for lat, lon in sample_points:
        res = requests.get(url, headers=headers, params={"x": str(lon), "y": str(lat)}).json()
        for doc in res.get("documents", []):
            if doc.get("region_type") == "H":
                r1 = doc.get("region_1depth_name", "")
                for key, zcode in REGION_NAME_TO_CODE.items():
                    if key in r1:
                        if zcode not in detected_codes:
                            detected_codes.add(zcode)
                            detected_names.append(key)
                        break
    return list(detected_codes), detected_names

def get_region_code_by_keyword(place_name):
    url = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"
    lat, lon = get_coords(place_name)
    if not lat:
        return "31"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    res = requests.get(url, headers=headers, params={"x": str(lon), "y": str(lat)}).json()
    for doc in res.get("documents", []):
        if doc.get("region_type") == "H":
            r1 = doc.get("region_1depth_name", "")
            for key, zcode in REGION_NAME_TO_CODE.items():
                if key in r1:
                    return zcode
    return "31"

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

def get_tesla_superchargers_by_radius(lat, lon, radius_km):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY.strip()}"}
    params = {
        "query": "테슬라 수퍼차저",
        "x": str(lon),
        "y": str(lat),
        "radius": int(radius_km * 1000)
    }
    res = requests.get(url, headers=headers, params=params).json()
    superchargers = {}
    for doc in res.get("documents", []):
        place_name = doc["place_name"]
        if "수퍼차저" in place_name or "슈퍼차저" in place_name:
            superchargers[doc["id"]] = {
                "name": place_name,
                "operator": "테슬라 슈퍼차저",
                "addr": doc.get("road_address_name") or doc.get("address_name"),
                "kw": TESLA_SUPERCHARGER_KW,
                "price": TESLA_SUPERCHARGER_PRICE,
                "price_str": f"{TESLA_SUPERCHARGER_PRICE}원/kWh (현장변동)"
            }
    return superchargers

def get_tesla_superchargers_by_route(route_coords, max_dist):
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

# --- 웹 화면 구성 ---
st.set_page_config(page_title="EV & Running Hub", page_icon="⚡")
st.subheader("⚡ 전기차 & 러닝 통합 매니저")

tab1, tab2, tab3 = st.tabs(["🚗 충전소 (경로)", "📍 충전소 (반경)", "🏃‍♂️ 러닝 코스 지도"])

# 탭 1: 경로 검색
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        start_place = st.text_input("출발지", value="대공원한신더휴", key="t1_start")
    with col2:
        end_place = st.text_input("목적지", value="솔봉숯불구이", key="t1_end")

    max_dist = st.slider("경로 이탈 허용 거리 (km)", 0.5, 5.0, 2.0, 0.5, key="route_slider")

    if st.button("경로 주변 최저가 찾기", type="primary", use_container_width=True, key="btn_t1"):
        s_lat, s_lon = get_coords(start_place)
        e_lat, e_lon = get_coords(end_place)
        
        if not s_lat or not e_lat:
            st.error("위치를 찾을 수 없습니다. 정확한 장소명을 입력해 주세요.")
        else:
            with st.spinner("경로 분석 및 공개 충전소 탐색 중..."):
                route = get_route_coords(s_lat, s_lon, e_lat, e_lon)
                region_codes, region_names = detect_regions_from_route(route)
                st.caption(f"📍 경유 지역: {', '.join(region_names)}")
                
                all_chargers = []
                for zcode in region_codes:
                    all_chargers.extend(get_chargers(zcode))

                categorized = {"초급속(200kW+)": {}, "급속(50~100kW)": {}, "완속(20~30kW)": {}}

                for ch in all_chargers:
                    if ch.get("limitYn") == "Y" or ch.get("stat") != "2":
                        continue
                    std_operator = match_operator(ch.get("busiId", ""), ch.get("busiNm", ""))
                    if not std_operator:
                        continue
                    try:
                        c_lat, c_lon = float(ch["lat"]), float(ch["lng"])
                    except (ValueError, TypeError):
                        continue
                    if not any(haversine(r_lat, r_lon, c_lat, c_lon) <= max_dist for r_lat, r_lon in route):
                        continue

                    out_str = str(ch.get("output", "0")).strip()
                    kw = int(out_str) if out_str.isdigit() else 0
                    s_type, p_key = classify_charger_speed(kw)
                    if not s_type:
                        continue

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

                tesla_stations = get_tesla_superchargers_by_route(route, max_dist)
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

# 탭 2: 반경 검색
with tab2:
    center_place = st.text_input("기준 위치 (주소 또는 장소명)", value="울산시청", key="t2_center")
    radius_km = st.slider("반경 거리 선택 (km)", 1.0, 20.0, 3.0, 1.0, key="radius_slider")

    if st.button("주변 반경 내 최저가 찾기", type="primary", use_container_width=True, key="btn_t2"):
        c_lat, c_lon = get_coords(center_place)
        
        if not c_lat:
            st.error("기준 위치를 찾을 수 없습니다.")
        else:
            with st.spinner(f"'{center_place}' 반경 {radius_km}km 이내 공개 충전소 검색 중..."):
                zcode = get_region_code_by_keyword(center_place)
                chargers = get_chargers(zcode)

                categorized = {"초급속(200kW+)": {}, "급속(50~100kW)": {}, "완속(20~30kW)": {}}

                for ch in chargers:
                    if ch.get("limitYn") == "Y" or ch.get("stat") != "2":
                        continue
                    std_operator = match_operator(ch.get("busiId", ""), ch.get("busiNm", ""))
                    if not std_operator:
                        continue
                    try:
                        lat, lon = float(ch["lat"]), float(ch["lng"])
                    except (ValueError, TypeError):
                        continue
                    if haversine(c_lat, c_lon, lat, lon) > radius_km:
                        continue

                    out_str = str(ch.get("output", "0")).strip()
                    kw = int(out_str) if out_str.isdigit() else 0
                    s_type, p_key = classify_charger_speed(kw)
                    if not s_type:
                        continue

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

                tesla_stations = get_tesla_superchargers_by_radius(c_lat, c_lon, radius_km)
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

# 탭 3: 러닝 코스 지도 (핀셋 클릭 지정 방식)
with tab3:
    st.markdown("### 🏃‍♂️ 지도 클릭으로 러닝 코스 만들기")

    # 세션 상태 초기화 (대공원한신더휴 기본 좌표)
    if "run_start_pt" not in st.session_state:
        st.session_state.run_start_pt = (35.5323, 129.3080)
    if "run_end_pt" not in st.session_state:
        st.session_state.run_end_pt = (35.5458, 129.2930)
    if "map_center" not in st.session_state:
        st.session_state.map_center = [35.5380, 129.3000]

    # 빠른 장소 이동 검색창
    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        search_loc = st.text_input("지도 중심 빠른 이동 (동네/공원명)", value="대공원한신더휴", label_visibility="collapsed")
    with col_s2:
        if st.button("이동", use_container_width=True):
            lat, lon = get_coords(search_loc)
            if lat:
                st.session_state.map_center = [lat, lon]
                st.session_state.run_start_pt = (lat, lon)
                st.rerun()

    # 모드 선택
    course_type = st.radio(
        "코스 만들기 방식",
        ["📍 지도에 직접 출발/도착 핀 찍기", "🔄 목표 거리(km) 입력 후 자동 왕복 코스"],
        horizontal=True
    )

    if course_type == "📍 지도에 직접 출발/도착 핀 찍기":
        click_mode = st.radio(
            "지금 지도에서 터치할 핀을 고르세요:",
            ["🟢 출발지 핀 찍기", "🔴 도착지(반환점) 핀 찍기"],
            horizontal=True
        )
    else:
        st.caption("💡 지도를 터치하면 그 위치가 '출발지'로 변경됩니다.")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            target_km = st.slider("목표 왕복 거리 (km)", 2.0, 20.0, 5.0, 0.5)
        with col_d2:
            direction_opt = st.selectbox("코스 방향 선택", ["북쪽(태화강 방향)", "동쪽", "남쪽(대공원 방향)", "서쪽"])
        
        dir_angles = {"북쪽(태화강 방향)": 0, "동쪽": 90, "남쪽(대공원 방향)": 180, "서쪽": 270}
        # 직선 대비 실제 도보 굴곡률(약 1.3배)을 감안해 반환점 계산
        half_straight_km = (target_km / 2.0) / 1.25
        s_lat, s_lon = st.session_state.run_start_pt
        t_lat, t_lon = calculate_destination_point(s_lat, s_lon, half_straight_km, dir_angles[direction_opt])
        st.session_state.run_end_pt = (t_lat, t_lon)

    # 경로 및 거리 실시간 계산 (보행자/산책로 우선)
    s_lat, s_lon = st.session_state.run_start_pt
    e_lat, e_lon = st.session_state.run_end_pt
    route_pts, one_way_km = get_walking_route(s_lat, s_lon, e_lat, e_lon)

    if course_type == "📍 지도에 직접 출발/도착 핀 찍기":
        st.success(f"🏃‍♂️ **편도 거리:** {one_way_km:.2f} km  |  **왕복 시:** {one_way_km*2:.2f} km")
    else:
        st.success(f"🔄 **자동 설계된 왕복 러닝 거리:** 약 **{one_way_km*2:.2f} km** (반환점까지 편도 {one_way_km:.2f} km)")

    # 지도 그리기
    m = folium.Map(location=st.session_state.map_center, zoom_start=14)

    # 출발지 핀
    folium.Marker(
        [s_lat, s_lon],
        tooltip="출발지 (초록 핀)",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)

    # 도착지(반환점) 핀
    folium.Marker(
        [e_lat, e_lon],
        tooltip="도착/반환점 (빨강 핀)",
        icon=folium.Icon(color="red", icon="flag")
    ).add_to(m)

    # 러닝 코스 라인
    if route_pts:
        folium.PolyLine(
            route_pts,
            color="#FF4B4B",
            weight=5,
            opacity=0.85
        ).add_to(m)

    # 지도를 화면에 띄우고 사용자의 클릭(터치) 좌표를 즉시 감지
    map_data = st_folium(m, width="100%", height=480, returned_objects=["last_clicked"])

    if map_data and map_data.get("last_clicked"):
        clicked_lat = map_data["last_clicked"]["lat"]
        clicked_lon = map_data["last_clicked"]["lng"]
        new_pt = (clicked_lat, clicked_lon)

        if course_type == "📍 지도에 직접 출발/도착 핀 찍기":
            if "출발지" in click_mode and new_pt != st.session_state.run_start_pt:
                st.session_state.run_start_pt = new_pt
                st.session_state.map_center = [clicked_lat, clicked_lon]
                st.rerun()
            elif "도착지" in click_mode and new_pt != st.session_state.run_end_pt:
                st.session_state.run_end_pt = new_pt
                st.session_state.map_center = [clicked_lat, clicked_lon]
                st.rerun()
        else:
            if new_pt != st.session_state.run_start_pt:
                st.session_state.run_start_pt = new_pt
                st.session_state.map_center = [clicked_lat, clicked_lon]
                st.rerun()
