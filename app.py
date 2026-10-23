import streamlit as st
import streamlit.components.v1 as components
import requests
import math
import folium

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

# 탭 3: 러닝 코스 지도 연동
with tab3:
    st.markdown("### 🏃‍♂️ 러닝 코스 지도 확인")
    
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        r_start = st.text_input("출발지 (현재위치/장소명)", value="태화강국가정원", key="run_start")
    with col_r2:
        r_end = st.text_input("도착지 (반환점/목적지)", value="울산대공원 동문", key="run_end")
        
    if st.button("🗺️ 지도에 러닝 코스 그리기", type="primary", use_container_width=True):
        rs_lat, rs_lon = get_coords(r_start)
        re_lat, re_lon = get_coords(r_end)
        
        if not rs_lat or not re_lat:
            st.error("장소 위치를 찾을 수 없습니다. 정확한 건물명이나 지명을 적어주세요.")
        else:
            with st.spinner("경로를 지도 위에 그리는 중..."):
                route_pts = get_route_coords(rs_lat, rs_lon, re_lat, re_lon)
                
                total_km = 0.0
                for i in range(len(route_pts) - 1):
                    total_km += haversine(route_pts[i][0], route_pts[i][1], route_pts[i+1][0], route_pts[i+1][1])
                
                st.success(f"🎯 **{r_start}** ➔ **{r_end}** 러닝 코스 거리: **{total_km:.2f} km**")
                
                # 1. Folium 지도 객체 생성
                mid_lat = (rs_lat + re_lat) / 2
                mid_lon = (rs_lon + re_lon) / 2
                m = folium.Map(location=[mid_lat, mid_lon], zoom_start=13)
                
                # 2. 마커 추가
                folium.Marker(
                    [rs_lat, rs_lon],
                    popup=f"출발: {r_start}",
                    tooltip="출발지",
                    icon=folium.Icon(color="green", icon="play")
                ).add_to(m)
                
                folium.Marker(
                    [re_lat, re_lon],
                    popup=f"도착: {r_end}",
                    tooltip="도착지",
                    icon=folium.Icon(color="red", icon="flag")
                ).add_to(m)
                
                # 3. 경로 선 그리기
                if route_pts:
                    folium.PolyLine(
                        route_pts,
                        color="#2B82F6",
                        weight=5,
                        opacity=0.8,
                        tooltip=f"러닝 코스 ({total_km:.2f}km)"
                    ).add_to(m)
                
                # 4. 스트림릿 HTML 렌더러로 고정 (새로고침 풀림 버그 방지)
                map_html = m._repr_html_()
                components.html(map_html, height=500, scrolling=False)
