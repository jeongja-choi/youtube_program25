import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# API 키/지역 설정: 기본은 .env에서 읽고, Streamlit Secrets가 있으면 덮어쓰기
API_KEY: Optional[str] = os.getenv("YOUTUBE_API_KEY")
try:
    # secrets.toml이 없을 경우 Streamlit이 예외를 던지므로 안전하게 감싼다
    API_KEY = st.secrets["YOUTUBE_API_KEY"]  # type: ignore[index]
except Exception:
    pass

DEFAULT_REGION = os.getenv("YOUTUBE_REGION_CODE", "US")
try:
    # 존재하면 secrets 값으로 덮어쓰기, 없거나 secrets.toml이 없으면 그대로 유지
    DEFAULT_REGION = st.secrets.get("YOUTUBE_REGION_CODE", DEFAULT_REGION)  # type: ignore[attr-defined]
except Exception:
    pass

st.set_page_config(page_title="YouTube Popular Videos", page_icon="📺", layout="wide")

st.title("📺 YouTube 인기 동영상 Top 30")
st.caption("YouTube Data API v3를 사용하여 지역별 인기 동영상을 간단히 보여주는 데모 앱입니다.")

# --- Sidebar: Settings ---
with st.sidebar:
    st.header("설정")
    
    # 검색 기능
    search_query = st.text_input("제목 또는 채널명 검색", key="search_input")
    
    # 국가 선택 (다중 선택 가능)
    countries = [
        "KR", "US", "JP", "GB", "BR", "IN", "DE", "FR", "RU", "CA",
        "AU", "MX", "ES", "IT", "ID", "TR", "NL", "SA", "TH", "VN"
    ]
    selected_countries = st.multiselect(
        "비교할 국가 선택 (최대 3개)",
        options=countries,
        default=[DEFAULT_REGION],
        max_selections=3,
        key="country_selector"
    )
    
    # 정렬 기준
    sort_by = st.selectbox(
        "정렬 기준",
        options=["조회수", "좋아요 수", "댓글 수", "최신 순"],
        index=0,
        key="sort_by_selector"
    )

# --- Refresh state ---
if "_refresh_ts" not in st.session_state:
    st.session_state["_refresh_ts"] = 0.0

if st.button("🔄 새로고침", key="refresh_button_main"):
    # Update a timestamp in session state to bust cache
    st.session_state["_refresh_ts"] = time.time()


def format_number(n: int) -> str:
    """큰 숫자를 K, M 단위로 포맷팅"""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

@st.cache_data(show_spinner=False, ttl=300)  # 5분 캐시
def fetch_popular_videos(
    api_key: str,
    region: str,
    max_results: int,
    search_query: str = "",
    refresh_key: float = 0.0,  # 캐시 무효화용
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """YouTube API를 사용하여 인기 동영상 또는 검색 결과를 가져옵니다."""
    _ = refresh_key  # 캐시 무효화용
    
    # 검색 쿼리가 있는 경우 검색 API 사용
    if search_query:
        search_url = "https://www.googleapis.com/youtube/v3/search"
        search_params = {
            "part": "snippet",
            "q": search_query,
            "type": "video",
            "maxResults": max_results,
            "regionCode": region,
            "key": api_key,
        }
        search_resp = requests.get(search_url, params=search_params, timeout=15)
        
        if search_resp.status_code != 200:
            raise RuntimeError(f"검색 API 오류: {search_resp.text}")
            
        video_ids = [item['id']['videoId'] for item in search_resp.json().get('items', [])]
        
        if not video_ids:
            return [], {}
            
        # 비디오 상세 정보 가져오기
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        }
    else:
        # 인기 동영상 가져오기
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "maxResults": max_results,
            "regionCode": region,
            "key": api_key,
        }

    resp = requests.get(url, params=params, timeout=15)

    if resp.status_code != 200:
        try:
            err_payload = resp.json()
        except Exception:
            err_payload = {"message": resp.text}
        raise RuntimeError(f"YouTube API 오류: HTTP {resp.status_code} - {err_payload}")

    data = resp.json()
    items = []
    stats_summary = {
        "total_views": 0,
        "total_likes": 0,
        "total_comments": 0,
        "video_count": 0
    }

    for item in data.get("items", []):
        vid = item.get("id")
        snip = item.get("snippet", {})
        stats = item.get("statistics", {})
        
        # 통계 데이터 수집
        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))
        
        stats_summary["total_views"] += views
        stats_summary["total_likes"] += likes
        stats_summary["total_comments"] += comments
        stats_summary["video_count"] += 1
        
        # 썸네일 URL 가져오기
        thumbs = snip.get("thumbnails", {}) or {}
        thumb_url = (
            (thumbs.get("high") or {}).get("url") or
            (thumbs.get("medium") or {}).get("url") or
            (thumbs.get("default") or {}).get("url") or ""
        )

        items.append({
            "id": vid,
            "title": snip.get("title", "(제목 없음)"),
            "channel": snip.get("channelTitle", "(채널 정보 없음)"),
            "views": views,
            "likes": likes,
            "comments": comments,
            "thumbnail": thumb_url,
            "publishedAt": snip.get("publishedAt", ""),
            "region": region,
        })
    
    # 평균 계산
    if stats_summary["video_count"] > 0:
        stats_summary["avg_views"] = stats_summary["total_views"] / stats_summary["video_count"]
        stats_summary["avg_likes"] = stats_summary["total_likes"] / stats_summary["video_count"]
        stats_summary["avg_comments"] = stats_summary["total_comments"] / stats_summary["video_count"]
    
    return items, stats_summary


def format_views(n: int) -> str:
    return f"{n:,}회" if isinstance(n, int) else "-"


def display_statistics(stats_data: Dict[str, Dict[str, Any]]) -> None:
    """통계 차트를 표시합니다."""
    if not stats_data:
        return
        
    st.subheader("📊 통계 분석")
    
    # 데이터프레임 생성
    df = pd.DataFrame([
        {
            '지역': region,
            '평균 조회수': data['avg_views'],
            '평균 좋아요 수': data['avg_likes'],
            '평균 댓글 수': data['avg_comments'],
            '총 조회수': data['total_views'],
            '총 좋아요 수': data['total_likes'],
            '총 댓글 수': data['total_comments'],
        }
        for region, data in stats_data.items()
    ])
    
    # 차트 표시
    tab1, tab2 = st.tabs(["지역별 비교", "상세 통계"])
    
    with tab1:
        col1, col2 = st.columns(2)
        
        with col1:
            fig = px.bar(
                df, 
                x='지역', 
                y=['평균 조회수', '평균 좋아요 수', '평균 댓글 수'],
                title='지역별 평균 지표 비교',
                barmode='group',
                labels={'value': '수치', 'variable': '지표'}
            )
            st.plotly_chart(fig, use_container_width=True)
            
        with col2:
            # 좋아요 대비 댓글 비율
            df['좋아요 대비 댓글 비율'] = df['평균 댓글 수'] / df['평균 좋아요 수'].replace(0, 1)
            fig = px.pie(
                df, 
                values='총 조회수', 
                names='지역',
                title='지역별 조회수 점유율',
                hole=0.4
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        # 상세 통계 테이블
        st.dataframe(
            df.style.format({
                '평균 조회수': '{:,.0f}회',
                '평균 좋아요 수': '{:,.0f}개',
                '평균 댓글 수': '{:,.0f}개',
                '총 조회수': '{:,.0f}회',
                '총 좋아요 수': '{:,.0f}개',
                '총 댓글 수': '{:,.0f}개',
                '좋아요 대비 댓글 비율': '{:.2%}'
            }),
            use_container_width=True
        )

def display_videos(videos: List[Dict[str, Any]]) -> None:
    """동영상 목록을 표시합니다."""
    if not videos:
        st.warning("표시할 동영상이 없습니다.")
        return
        
    st.subheader(f"🎬 검색 결과 ({len(videos)}개)")
    
    # 정렬
    sort_options = {
        "조회수": "views",
        "좋아요 수": "likes",
        "댓글 수": "comments",
        "최신 순": "publishedAt"
    }
    
    # 그리드 레이아웃으로 표시
    cols_per_row = 3
    cols = st.columns(cols_per_row)
    
    for i, video in enumerate(videos):
        with cols[i % cols_per_row]:
            try:
                url = f"https://www.youtube.com/watch?v={video['id']}"
                
                # 썸네일
                if video["thumbnail"]:
                    st.image(video["thumbnail"], use_container_width=True)
                
                # 제목 (링크)
                st.markdown(f"**[{video['title']}]({url})**")
                
                # 채널 정보
                st.caption(f"👤 {video['channel']}")
                
                # 통계 (테이블 형식으로 표시)
                stats_html = f"""
                <style>
                    .stats-table {{
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 0.85em;
                        margin: 8px 0;
                    }}
                    .stats-table td {{
                        padding: 2px 0;
                        vertical-align: middle;
                    }}
                    .stats-table .icon {{
                        text-align: center;
                        width: 24px;
                    }}
                    .stats-table .value {{
                        text-align: right;
                        font-weight: 500;
                    }}
                </style>
                <table class="stats-table">
                    <tr>
                        <td class="icon">👁️</td>
                        <td>조회수</td>
                        <td class="value">{format_number(video['views'])}</td>
                    </tr>
                    <tr>
                        <td class="icon">👍</td>
                        <td>좋아요</td>
                        <td class="value">{format_number(video['likes'])}</td>
                    </tr>
                    <tr>
                        <td class="icon">💬</td>
                        <td>댓글</td>
                        <td class="value">{format_number(video['comments'])}</td>
                    </tr>
                </table>
                """
                st.markdown(stats_html, unsafe_allow_html=True)
                
                # 지역 태그
                if 'region' in video:
                    st.caption(f"🌍 {video['region']}")
                
                st.markdown("---")
                
            except Exception as e:
                st.error(f"동영상 표시 중 오류: {str(e)}")

def main() -> None:
    if not API_KEY:
        st.error(
            "YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일 또는 Streamlit Secrets에 API 키를 설정하세요."
        )
        with st.expander("설정 방법 보기"):
            st.markdown(
                """
                1) 프로젝트 루트에 `.env` 파일을 만들고 아래처럼 설정하세요.
                   
                   ```env
                   YOUTUBE_API_KEY=YOUR_API_KEY
                   YOUTUBE_REGION_CODE=US
                   ```
                
                또는
                
                2) `.streamlit/secrets.toml` 파일에 설정:
                   
                   ```toml
                   YOUTUBE_API_KEY = "YOUR_API_KEY"
                   ```
                """
            )
        return

    # 사이드바 설정
    with st.sidebar:
        st.header("🔍 검색")
        search_query = st.text_input("제목 또는 채널명 검색", key="main_search_input")
        
        st.header("🌍 국가 설정")
        countries = ["KR", "US", "JP", "GB", "BR", "IN", "DE", "FR", "RU", "CA",
                   "AU", "MX", "ES", "IT", "ID", "TR", "NL", "SA", "TH", "VN"]
        selected_countries = st.multiselect(
            "비교할 국가 선택 (최대 3개)",
            options=countries,
            default=[DEFAULT_REGION],
            max_selections=3,
            key="main_country_selector"
        )
        
        st.header("⚙️ 정렬")
        sort_by = st.selectbox(
            "정렬 기준",
            options=["조회수", "좋아요 수", "댓글 수", "최신 순"],
            index=0,
            key="main_sort_by_selector"
        )
        
        st.markdown("---")
        st.markdown("### 정보")
        st.markdown("YouTube Data API v3를 사용하여 인기 동영상을 표시합니다.")
        
        if st.button("🔄 새로고침", key="refresh_button_sidebar"):
            st.session_state["_refresh_ts"] = time.time()

    try:
        all_videos = []
        stats_data = {}
        
        # 선택된 국가별로 데이터 가져오기
        for country in selected_countries:
            with st.spinner(f"{country} 지역 데이터를 불러오는 중..."):
                videos, stats = fetch_popular_videos(
                    api_key=API_KEY,
                    region=country,
                    max_results=10,  # 국가당 10개씩
                    search_query=search_query if search_query else "",
                    refresh_key=st.session_state.get("_refresh_ts", 0.0)
                )
                
                if stats:  # 통계 데이터가 있는 경우에만 추가
                    stats_data[country] = stats
                
                # 국가 정보 추가
                for v in videos:
                    v['region'] = country
                all_videos.extend(videos)
        
        # 정렬
        sort_key = {
            "조회수": "views",
            "좋아요 수": "likes",
            "댓글 수": "comments",
            "최신 순": "publishedAt"
        }.get(sort_by, "views")
        
        all_videos.sort(key=lambda x: x.get(sort_key, 0), reverse=sort_by != "최신 순")
        
        # 통계 차트 표시
        if len(selected_countries) > 1:
            display_statistics(stats_data)
        
        # 동영상 목록 표시
        display_videos(all_videos)
        
    except Exception as e:
        st.error("데이터를 불러오는 중 오류가 발생했습니다.")
        st.exception(e)


if __name__ == "__main__":
    main()
