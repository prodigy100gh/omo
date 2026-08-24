# ==============================================================================
# [SECTION 1] 파이썬 내장 및 외부 라이브러리 (Setup & Dependencies)
# ==============================================================================
# 1. 파이썬 기본 내장 라이브러리
import json
import random
import os
import urllib.parse
import re
import time
import datetime
import hashlib
import ast # 💡 고장 난 JSON(작은따옴표 등)도 강제로 열어주는 마법의 모듈
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from youtubesearchpython import VideosSearch
from dotenv import load_dotenv

# 2. 외부 라이브러리 및 장고 프레임워크
import requests
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, OuterRef, Q, Subquery, Value, When, Avg
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

# 3. 로컬 앱 모델 및 폼 임포트
from .forms import SignupForm
from .models import Movie, TvSeries, Rating, Watchlist, TrailerReport

# 💡 현재 활성화된 유저 모델 가져오기 (가장 밑에 두는 것이 안전합니다)
User = get_user_model()

# 💡 2. 임포트문 바로 밑, 함수들이 시작되기 직전 꼭대기에 이렇게 딱 적어주세요!
load_dotenv()


def extract_youtube_id(url):
    """어떤 악조건의 링크가 들어와도 유튜브 11자리 ID를 악착같이 뽑아냅니다."""
    if not url: 
        return None
        
    url = url.strip()

    # 1. 만약 <iframe> 태그를 통째로 넣었다면 주소만 쏙 빼냅니다.
    if '<iframe' in url and 'src="' in url:
        match = re.search(r'src="([^"]+)"', url)
        if match:
            url = match.group(1)

    # 2. 다양한 유튜브 URL 패턴 분석
    try:
        if 'youtu.be/' in url:
            return url.split('youtu.be/')[1].split('?')[0][:11]
        elif 'shorts/' in url:
            return url.split('shorts/')[1].split('?')[0][:11]
        elif 'embed/' in url:
            return url.split('embed/')[1].split('?')[0][:11]
        elif 'watch' in url:
            parsed = urllib.parse.urlparse(url)
            v_param = urllib.parse.parse_qs(parsed.query).get('v')
            if v_param:
                return v_param[0][:11]
                
        # 3. 주소가 아니라 '11자리 ID' 문자열 자체만 입력했을 경우
        if len(url) == 11 and " " not in url:
            return url
            
    except Exception:
        pass

    return None


# ==============================================================================
# [SECTION 2] 전역 설정 및 헬퍼 함수 (Global Config & Helper Functions)
# ==============================================================================
# 💡 [초보자 안내] IMDb의 영문 장르 데이터를 한글로 예쁘게 매핑하기 위한 기본 테이블입니다.
IMDB_GENRE_MAP = {
    'Action': '액션', 'Adventure': '모험', 'Animation': '애니메이션',
    'Biography': '전기', 'Comedy': '코미디', 'Crime': '범죄',
    'Documentary': '다큐멘터리', 'Drama': '드라마', 'Family': '가족',
    'Fantasy': '판타지', 'Game-Show': '게임쇼', 'History': '역사',
    'Horror': '공포', 'Music': '음악', 'Musical': '뮤지컬',
    'Mystery': '미스터리', 'News': '뉴스', 'Reality-TV': '리얼리티',
    'Romance': '로맨스', 'Sci-Fi': 'SF', 'Short': '단편',
    'Sport': '스포츠', 'Talk-Show': '토크쇼', 'Thriller': '스릴러',
    'War': '전쟁', 'Western': '서부', 'Adult': '성인'
}

# 💡 [핵심] TMDB 영화/TV 및 IMDb의 모든 영문 장르를 -> 완벽한 표준 한글 장르로 변환하는 '마스터 사전'
STANDARD_GENRE_MAP = {
    # 📺 TV 시리즈 전용 복합 장르 (TMDB TV) - 쪼개서 리스트로 반환
    'Action & Adventure': ['액션', '모험'], 'Sci-Fi & Fantasy': ['SF', '판타지'],
    'War & Politics': ['전쟁', '역사'], 'Kids': ['가족', '어린이'],
    'Soap': ['드라마'], 'Reality': ['리얼리티'], 'Talk': ['토크쇼'],
    'News': ['뉴스'], 'TV Movie': ['TV 영화'],
    # 🎬 일반 단일 장르 (IMDb / TMDB Movie)
    'Action': ['액션'], 'Adventure': ['모험'], 'Animation': ['애니메이션'],
    'Biography': ['전기'], 'Comedy': ['코미디'], 'Crime': ['범죄'],
    'Documentary': ['다큐멘터리'], 'Drama': ['드라마'], 'Family': ['가족'],
    'Fantasy': ['판타지'], 'Game-Show': ['게임쇼'], 'History': ['역사'],
    'Horror': ['공포'], 'Music': ['음악'], 'Musical': ['뮤지컬'],
    'Mystery': ['미스터리'], 'Reality-TV': ['리얼리티'], 'Romance': ['로맨스'],
    'Sci-Fi': ['SF'], 'Science Fiction': ['SF'], 'Short': ['단편'],
    'Sport': ['스포츠'], 'Talk-Show': ['토크쇼'], 'Thriller': ['스릴러'],
    'War': ['전쟁'], 'Western': ['서부'], 'Adult': ['성인'],
}

# 💡 [글로벌 언어 매핑 사전] 원어 코드를 예쁜 한글로 변환
LANGUAGE_KR_MAP = {
    'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어(표준어)', 'cn': '중국어(광둥어)', 'yue': '광둥어', 
    'tw': '중국어(대만)', 'th': '태국어', 'id': '인도네시아어', 'vi': '베트남어', 'tl': '타갈로그어', 'ms': '말레이어',
    'fr': '프랑스어', 'es': '스페인어', 'de': '독일어', 'it': '이탈리아어', 'pt': '포르투갈어', 'ru': '러시아어', 
    'nl': '네덜란드어', 'pl': '폴란드어', 'uk': '우크라이나어', 'cs': '체코어', 'hu': '헝가리어', 'el': '그리스어', 
    'ro': '루마니아어', 'sv': '스웨덴어', 'da': '덴마크어', 'no': '노르웨이어', 'fi': '핀란드어',
    'ar': '아랍어', 'tr': '튀르키예어', 'he': '히브리어', 'fa': '페르시아어',
    'hi': '힌디어', 'ta': '타밀어', 'te': '텔루구어', 'ml': '말라얄람어'
}



# 💡 [헬퍼 1] 화면에 표시할 장르 텍스트 생성 (영문 복합 장르 완전 한글화)
def get_display_genre(tmdb_g, imdb_g):
    raw_str = str(tmdb_g or '').strip() if tmdb_g and str(tmdb_g).strip() not in ['None', '정보 없음', ''] else str(imdb_g or '').strip()
    if not raw_str or raw_str in ['None', '정보 없음', '']: return '정보 없음'

    kr_genres = []
    # 콤마나 슬래시로 1차 분리
    parts = [p.strip() for p in raw_str.replace('/', ',').split(',') if p.strip()]

    for part in parts:
        # 마스터 사전에 있으면 매핑, 없으면(이미 한글이거나 특이 장르) 원본 그대로 유지
        if part in STANDARD_GENRE_MAP: kr_genres.extend(STANDARD_GENRE_MAP[part])
        else: kr_genres.append(part)

    # 중복 제거 후 깔끔하게 콤마로 연결
    unique_kr = []
    for g in kr_genres:
        if g and g not in unique_kr and g != 'None': unique_kr.append(g)

    return ', '.join(unique_kr) if unique_kr else '정보 없음'

# 💡 [헬퍼 2] 개봉/방영 연도 추출 (TMDB 날짜 우선, 없으면 IMDb 연도)
def get_display_date(tmdb_d, imdb_d):
    if tmdb_d and str(tmdb_d).strip() and str(tmdb_d).strip() != 'None': return str(tmdb_d).strip()
    if imdb_d and str(imdb_d).strip() and str(imdb_d).strip() != 'None': return str(imdb_d)[:4]
    return "----"

# 💡 [헬퍼 3] 러닝타임(상영시간) 안전 추출 (음수나 오류 데이터 원천 차단)
def get_display_runtime(tmdb_r, imdb_r):
    if tmdb_r and str(tmdb_r).strip() not in ['None', '']:
        try:
            val = int(tmdb_r)
            if val > 0: return val
        except (ValueError, TypeError): pass
    if imdb_r and str(imdb_r).strip() not in ['None', '']:
        try:
            val = int(imdb_r)
            if val > 0: return val
        except (ValueError, TypeError): pass
    return 0

# 💡 [방어형 헬퍼 4] 필터 드롭다운용 장르 리스트 (어떤 페이지에서 호출해도 에러 0%)
def get_all_genres(queryset=None):
    try:
        # 안전망: queryset이 존재하고 model 속성이 있을 때만 검사합니다.
        if queryset is not None and hasattr(queryset, 'model') and queryset.model.__name__ == 'TvSeries':
            return [
                '드라마', '코미디', 'SF', '판타지', '범죄', '액션', '모험', 
                '미스터리', '애니메이션', '가족', '전쟁', '다큐멘터리', 
                '리얼리티', '토크쇼', '서부', '뉴스', '역사', '로맨스'
            ]
    except Exception:
        pass
    
    # 🎬 기본 영화 화면일 때 (에러 시에도 무조건 반환)
    return [
        '드라마', '코미디', '스릴러', '액션', '로맨스', '공포', '범죄', 
        '미스터리', '모험', '다큐멘터리', 'SF', '가족', '판타지', 'TV 영화', 
        '역사', '애니메이션', '음악', '전쟁', '서부'
    ]

# 💡 [헬퍼 5] 필터 및 상세페이지용 OTT 아이콘 및 텍스트 매핑 (구글 파비콘 API로 영구 고정!)
def get_ott_list_with_logos(queryset=None):
    return [
        # 🇰🇷 국내 및 메이저 OTT
        {'id': 'Netflix', 'name': '넷플릭스', 'logo': 'https://www.google.com/s2/favicons?domain=netflix.com&sz=128'},
#        {'id': 'Netflix Standard with Ads', 'name': '넷플릭스 광고형', 'logo': 'https://www.google.com/s2/favicons?domain=netflix.com&sz=128'},
        {'id': 'TVING', 'name': '티빙', 'logo': 'https://www.google.com/s2/favicons?domain=tving.com&sz=128'},
        {'id': 'Coupang Play', 'name': '쿠팡플레이', 'logo': 'https://www.google.com/s2/favicons?domain=coupangplay.com&sz=128'},
        {'id': 'Wavve', 'name': '웨이브', 'logo': '/static/images/Wavve_icon.png'}, # 로컬 이미지 유지
        {'id': 'Disney Plus', 'name': '디즈니+', 'logo': 'https://www.google.com/s2/favicons?domain=disneyplus.com&sz=128'},
        {'id': 'Watcha', 'name': '왓챠', 'logo': '/static/images/WATCHA_icon_Square.png'}, # 로컬 이미지 유지
        {'id': 'Apple TV Plus', 'name': '애플 TV+', 'logo': 'https://www.google.com/s2/favicons?domain=tv.apple.com&sz=128'},
        {'id': 'Amazon Prime Video', 'name': '아마존 프라임', 'logo': 'https://www.google.com/s2/favicons?domain=primevideo.com&sz=128'},
        
        # 🌍 해외/글로벌 OTT
        {'id': 'Sun Nxt', 'name': 'Sun Nxt', 'logo': 'https://www.google.com/s2/favicons?domain=sunnxt.com&sz=128'},
        {'id': 'FilmBox+', 'name': 'FilmBox+', 'logo': 'https://www.google.com/s2/favicons?domain=filmbox.com&sz=128'},
        {'id': 'MUBI', 'name': 'MUBI', 'logo': 'https://www.google.com/s2/favicons?domain=mubi.com&sz=128'},
        {'id': 'Bloodstream', 'name': 'Bloodstream', 'logo': ''}, # 불확실한 곳은 안전하게 빈칸(기본 아이콘) 처리
        {'id': 'Hoichoi', 'name': 'Hoichoi', 'logo': 'https://www.google.com/s2/favicons?domain=hoichoi.tv&sz=128'},
        {'id': 'DocAlliance Films', 'name': 'DocAlliance Films', 'logo': 'https://www.google.com/s2/favicons?domain=dafilms.com&sz=128'},
        {'id': 'Crunchyroll', 'name': 'Crunchyroll', 'logo': 'https://www.google.com/s2/favicons?domain=crunchyroll.com&sz=128'},
        {'id': 'KableOne', 'name': 'KableOne', 'logo': ''},
        {'id': 'Dekkoo', 'name': 'Dekkoo', 'logo': 'https://www.google.com/s2/favicons?domain=dekkoo.com&sz=128'},
        {'id': 'Magellan TV', 'name': 'Magellan TV', 'logo': 'https://www.google.com/s2/favicons?domain=magellantv.com&sz=128'},
        {'id': 'DOCSVILLE', 'name': 'DOCSVILLE', 'logo': 'https://www.google.com/s2/favicons?domain=docsville.com&sz=128'},
        {'id': 'Curiosity Stream', 'name': 'Curiosity Stream', 'logo': 'https://www.google.com/s2/favicons?domain=curiositystream.com&sz=128'},
    ]


# ==============================================================================
# [SECTION 3] 계정 및 온보딩 뷰 (Authentication & Onboarding)
# ==============================================================================
# --- 회원가입 뷰 ---
def signup_view(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            # 💡 [핵심 해결] 가입 후 세션 충돌 방지를 위해 인증 백엔드를 명시적으로 지정
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)  # 가입 즉시 자동 로그인
            # 평점이 0개이므로 무조건 온보딩으로 토스!
            return redirect('onboarding')
    else:
        form = SignupForm()
    return render(request, 'movie/signup.html', {'form': form})

# --- 로그인 뷰 (이전 주소 스마트 기억 장치 탑재) ---
def login_view(request):
    # 주소창에 ?next=/movie/123 이 있으면 세션에 몰래 숨겨둡니다.
    if request.method == 'GET' and 'next' in request.GET:
        request.session['next_url'] = request.GET['next']

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # 세션에서 원래 가려던 목적지를 꺼냄 (없으면 home)
            next_url = request.session.pop('next_url', 'home')
            
            # 💡 [핵심 버그 수정] 에러가 나던 user.ratings를 안전한 방식인 Rating.objects.filter(user=user)로 교체!
            if Rating.objects.filter(user=user).count() < 10:
                return redirect('onboarding') 
            return redirect(next_url) 
    else:
        form = AuthenticationForm(request)
    return render(request, 'movie/login.html', {'form': form})

# --- 로그아웃 뷰 ---
def logout_view(request):
    next_url = request.GET.get('next', 'home')
    logout(request)
    # 로그아웃 직전에 보고 있던 페이지로 깔끔하게 돌려보냄
    return redirect(next_url)

# --- 온보딩 뷰 (영화 50편 + TV 20편 스마트 분배 로직) ---
@login_required
def onboarding_view(request):
    # 💡 국가별 인구수/투표수 차이를 반영한 공정한 기준 컷 (인도 영화 왜곡 방지)
    vote_condition = (
        Q(tmdb_production_country_kr__icontains='한국', imdb_vote_count__gte=300) |
        Q(tmdb_production_country_kr__icontains='일본', imdb_vote_count__gte=300) |
        Q(tmdb_production_country_kr__icontains='인도', imdb_vote_count__gte=10000) |
        (~Q(tmdb_production_country_kr__icontains='한국') & ~Q(tmdb_production_country_kr__icontains='일본') & ~Q(tmdb_production_country_kr__icontains='인도') & Q(imdb_vote_count__gte=5000))
    )

    selected_movies = []
    selected_ids = set()

    # 1. 한국인이 가장 사랑하는 5대 장르 한국 영화 최소 10개 확보
    korean_genres = ['액션', '드라마', '코미디', '스릴러', '범죄']
    korean_count = 0
    for genre in korean_genres:
        k_movies = Movie.objects.filter(vote_condition, imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]', tmdb_production_country_kr__icontains='한국', tmdb_genre__icontains=genre).exclude(id__in=selected_ids).order_by('-imdb_vote_count')[:2]
        for m in k_movies:
            selected_movies.append(m); selected_ids.add(m.id); korean_count += 1
            
    # 한국 영화 10개가 안 채워졌다면 인기순으로 마저 보충
    if korean_count < 10:
        extra_k_movies = Movie.objects.filter(vote_condition, imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]', tmdb_production_country_kr__icontains='한국').exclude(id__in=selected_ids).order_by('-imdb_vote_count')[:10 - korean_count]
        for m in extra_k_movies: selected_movies.append(m); selected_ids.add(m.id)

    # 2. 일본 실사 영화 (애니 제외) 2개 강제 추가
    japanese_live_movies = Movie.objects.filter(vote_condition, imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]', tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').exclude(id__in=selected_ids).order_by('-imdb_vote_count')[:2]
    for m in japanese_live_movies: selected_movies.append(m); selected_ids.add(m.id)

    # 3. 글로벌 영화: 10대 장르별 2개씩 골고루 추출
    target_genres = ['SF', '공포', '드라마', '스릴러', '액션', '애니메이션', '코미디', '다큐멘터리', '전쟁', '판타지']
    for genre in target_genres:
        genre_movies = Movie.objects.filter(vote_condition, imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]', tmdb_genre__icontains=genre).exclude(id__in=selected_ids).order_by('-imdb_vote_count')[:2]
        for m in genre_movies: selected_movies.append(m); selected_ids.add(m.id)

    # 4. 남은 자리(50개 풀)는 글로벌 초대작 인기순으로 채움
    remaining_count = 50 - len(selected_movies)
    if remaining_count > 0:
        extra_movies = Movie.objects.filter(vote_condition, imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]').exclude(id__in=selected_ids).order_by('-imdb_vote_count')[:remaining_count]
        for m in extra_movies: selected_movies.append(m); selected_ids.add(m.id)

    # ==========================================
    # 📺 5. TV 시리즈 전용 20개 추출 로직
    # ==========================================
    selected_series = []
    selected_series_ids = set()

    # 한국 TV 시리즈 5개 강제 확보
    korean_series = TvSeries.objects.filter(imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]', tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:5]
    for s in korean_series: selected_series.append(s); selected_series_ids.add(s.id)

    # 나머지 15개는 글로벌 인기 시리즈로 보충
    remaining_s_count = 20 - len(selected_series)
    if remaining_s_count > 0:
        extra_series = TvSeries.objects.filter(imdb_rating__gte=7.0, tmdb_title__regex=r'[가-힣]').exclude(id__in=selected_series_ids).order_by('-imdb_vote_count')[:remaining_s_count]
        for s in extra_series: selected_series.append(s); selected_series_ids.add(s.id)

    # 화면에 늘 같은 순서로 나오면 지루하므로 배열 섞기!
    random.shuffle(selected_movies)
    random.shuffle(selected_series)

    # 유저가 이 화면에서 이전에 매겨둔 평점이 있다면 숫자를 채워주기 위한 매핑
    if request.user.is_authenticated:
        user_ratings = Rating.objects.filter(user=request.user)
        rating_count = user_ratings.count()
        movie_ratings_dict = {r.movie_id: r.score for r in user_ratings if r.movie_id}
        tv_ratings_dict = {r.tvseries_id: r.score for r in user_ratings if r.tvseries_id}
    else:
        rating_count = 0; movie_ratings_dict = {}; tv_ratings_dict = {}

    for item in selected_movies + selected_series:
        if isinstance(item, Movie):
            item.user_score = movie_ratings_dict.get(item.id, 0)
        else:
            item.user_score = tv_ratings_dict.get(item.id, 0)
        
        # 🚀 온보딩용 장르 텍스트 (단축+ 없이 콤마로 풀 네임 표기)
        item.display_genre = get_display_genre(getattr(item, 'tmdb_genre', ''), getattr(item, 'imdb_genre', ''))
        
        # 투표수 단위를 K, M 등으로 예쁘게 변환
        try: votes = int(item.imdb_vote_count) if item.imdb_vote_count else 0
        except ValueError: votes = 0

        if votes <= 0: item.display_votes = "0"
        elif votes >= 995000000000: item.display_votes = f"{votes / 1000000000000:.1f}T"
        elif votes >= 995000000: item.display_votes = f"{votes / 1000000000:.1f}B"
        elif votes >= 995000: item.display_votes = f"{votes / 1000000:.1f}M"
        elif votes >= 1000: item.display_votes = f"{votes / 1000:.1f}K"
        else: item.display_votes = str(votes)

    return render(request, 'movie/onboarding.html', {
        'movies': selected_movies,
        'series_list': selected_series,
        'current_count': rating_count,
        'rating_range': range(1, 11), 
    })

# --- 온보딩 초기화 뷰 ---
@login_required
def reset_ratings(request):
    if request.method == 'POST':
        # 현재 로그인한 유저의 모든 평가 기록을 DB에서 삭제 (완전 초기화)
        Rating.objects.filter(user=request.user).delete()
    return redirect('onboarding')

# ==============================================================================
# [SECTION 4] 맞춤형 AI 추천 엔진 코어 (Gemini AI Core Logic)
# ==============================================================================
# 💡 [초보자 안내] 구글 제미나이(Gemini) AI를 호출하여 '사용자가 높은 점수를 준 작품'을 기반으로
# 취향을 심층 분석하고, 영화와 TV 시리즈를 각각 40개씩 엄선하는 핵심 AI 엔진입니다.

def get_gemini_recommendations(user, base_pool):
    try:
        from google.genai import Client
        from google.genai import types
        
        # ==========================================================================
        # [PHASE 1: 캐시 및 사용자가 이미 본(평가/찜) 영화 데이터 필터링]
        # ==========================================================================
        cache_key = f"gemini_recs_v5_{user.id}"
        cached_pool_ids = cache.get(cache_key)
        
        # 💡 [핵심 버그 수정 적용] 영화 평가만 정확히 가져오도록 필터 추가 (movie__isnull=False)
        rated_ids = set(Rating.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True))
        watchlisted_ids = set(Watchlist.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True))
        seen_ids = rated_ids | watchlisted_ids

        if cached_pool_ids and len(cached_pool_ids) > 10:
            interacted_count = sum(1 for mid in cached_pool_ids if mid in rated_ids) # 💡 찜 빼고 평가만 카운트!
            
            if interacted_count < 10:
                unseen_ids = [mid for mid in cached_pool_ids if mid not in seen_ids]
                if len(unseen_ids) >= 10:
                    print(f"  ✅ [캐시 적중] {len(unseen_ids)}개의 남은 풀에서 10개를 무작위 추출합니다!")
                    display_ids = random.sample(unseen_ids, 10)
                    movies_dict = {m.id: m for m in Movie.objects.filter(id__in=display_ids)}
                    return [movies_dict[mid] for mid in display_ids if mid in movies_dict]
            else:
                print("  🔄 [AI] 영화 10개 평가 완료! 취향 변화를 반영하여 TV 시리즈도 함께 재가동합니다...")
                cache.delete(f"gemini_tv_recs_v5_{user.id}")
                cache.delete(f"gemini_tv_fallback_v7_{user.id}")

        print("  🤖 [AI] Gemini 고차원 심층 분석 로직 진입...")
        client = Client(api_key=settings.GEMINI_API_KEY)

        # ==========================================================================
        # [PHASE 2: 사용자 취향 영화 분석 & 동일 조건 TV 시리즈 동시 추출]
        # ==========================================================================
        high_ratings = list(Rating.objects.filter(user=user, score__gte=8, movie__isnull=False).select_related('movie')[:50])
        if not high_ratings:
            high_ratings = list(Rating.objects.filter(user=user, score__gte=6, movie__isnull=False).select_related('movie')[:50])

        if not high_ratings: return []

        movie_eval_count = len(high_ratings)
        favorite_tv_info = []
        if movie_eval_count > 0:
            fav_genres = [g.strip() for r in high_ratings for g in get_display_genre(r.movie.tmdb_genre, r.movie.imdb_genre).split(',') if g.strip() and g.strip() != '정보 없음']
            top_genre_names = [g for g, c in Counter(fav_genres).most_common(3)]
            
            tv_query = TvSeries.objects.exclude(
                Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | 
                Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
            ).filter(imdb_rating__gte=7.5)
            
            if top_genre_names:
                tv_genre_q = Q()
                for g in top_genre_names: tv_genre_q |= Q(tmdb_genre__icontains=g) | Q(imdb_genre__icontains=g)
                tv_query = tv_query.filter(tv_genre_q)
                
            matched_tv_series = list(tv_query.order_by('-imdb_vote_count')[:movie_eval_count])
            favorite_tv_info = [
                f"'{tv.tmdb_title}' (TV시리즈, {get_display_date(tv.tmdb_release_date, tv.imdb_release_date)[:4]}년, 국가: {tv.tmdb_production_country_kr}, 장르: {get_display_genre(tv.tmdb_genre, tv.imdb_genre)}, 줄거리: {str(tv.tmdb_overview)[:60]}..., 키워드: {str(tv.tmdb_keywords)[:40]})" 
                for tv in matched_tv_series
            ]

        ott_list = []
        for r in high_ratings:
            if r.movie.tmdb_streaming_providers:
                for prov in r.movie.tmdb_streaming_providers: ott_list.append(prov.get('provider_name'))

        top_otts = [ott for ott, count in Counter(ott_list).most_common(2)]
        ott_prompt = ""
        if top_otts:
            ott_prompt = f"\n        4. 스트리밍 최적화: 사용자는 주로 [{', '.join(top_otts)}] 플랫폼을 이용합니다. 제공된 [추천 후보 목록]의 'ott' 필드를 확인하여, 가급적 해당 플랫폼에서 시청 가능한 영화에 가산점을 부여하세요."

        favorite_info = [
            f"'{r.movie.tmdb_title}' ({get_display_date(r.movie.tmdb_release_date, r.movie.imdb_release_date)[:4]}년, 국가: {r.movie.tmdb_production_country_kr}, 장르: {get_display_genre(r.movie.tmdb_genre, r.movie.imdb_genre)}, 줄거리: {str(r.movie.tmdb_overview)[:80]}..., 키워드: {str(r.movie.tmdb_keywords)[:50]}, 내 평점: {r.score}/10점)" 
            for r in high_ratings
        ]

        # ==========================================================================
        # [PHASE 3: AI에게 제시할 추천 후보 목록(풀) 60개 엄선]
        # ==========================================================================
        valid_pool = base_pool.exclude(id__in=seen_ids).exclude(
            Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | 
            Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
        ).filter(Q(tmdb_title__regex=r'[가-힣]') | Q(tmdb_production_country_kr__icontains='한국'))

        kr_candidates = list(valid_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:50])
        jp_candidates = list(valid_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:50])
        kr_pool = random.sample(kr_candidates, min(10, len(kr_candidates)))
        jp_pool = random.sample(jp_candidates, min(10, len(jp_candidates)))
        
        exclude_ids = [m.id for m in kr_pool + jp_pool]
        others_candidates = list(valid_pool.exclude(id__in=exclude_ids).order_by('-imdb_vote_count')[:150])
        others_pool = random.sample(others_candidates, min(40, len(others_candidates)))
        combined_candidates = kr_pool + jp_pool + others_pool
        
        if not combined_candidates: return []

        candidate_info = [{
            "id": m.id, "title": m.tmdb_title if re.search(r'[가-힣]', str(m.tmdb_title or '')) else getattr(m, 'translated_title', m.tmdb_title), 
            "year": get_display_date(m.tmdb_release_date, m.imdb_release_date)[:4],
            "country": str(m.tmdb_production_country_kr or '정보 없음'), "genre": get_display_genre(m.tmdb_genre, m.imdb_genre),
            "overview": str(m.tmdb_overview)[:150], "keywords": str(m.tmdb_keywords)[:80],
            "ott": ", ".join([p.get('provider_name') for p in m.tmdb_streaming_providers]) if m.tmdb_streaming_providers else "정보 없음"
        } for m in combined_candidates]

        # ==========================================================================
        # [PHASE 4: 구글 제미나이(Gemini) AI 프롬프트 구성 및 통신 요청]
        # ==========================================================================
        # 💡 [정교한 원본 프롬프트 완벽 복구]
        prompt = f"""
        당신은 세계 최고 수준의 영화 평론가이자 맞춤형 AI 큐레이터입니다.
        단순히 텍스트로 주어진 장르나 국가를 매칭하는 수준을 넘어서, 당신이 가진 방대한 '영화 데이터베이스(사전 학습된 지식)'를 총동원하여 고차원적인 분석을 수행하세요.

        [분석 대상 1: 사용자가 좋아하는 상위 영화 목록]
        {', '.join(favorite_info)}

        [분석 대상 2: 사용자 취향 조건과 일치하는 상위 TV 시리즈 목록 (서사 취향 참고용)]
        {', '.join(favorite_tv_info)}

        [분석 지시사항]
        1. 심층 취향 프로파일링: 위 영화 및 TV 시리즈 목록을 보고 이 사용자가 선호하는 영화의 '핵심 테마', '분위기(Mood)', '서사 구조(예: 반전, 열린 결말, 영웅 서사)', '선호하는 연출 스타일(감독)' 등을 심층적으로 유추하세요.
        2. 후보군 지식 활성화: 아래 [추천 후보 목록]에 있는 영화들의 실제 줄거리, 톤앤매너, 작품성을 당신의 지식 안에서 떠올리세요.
        3. 완벽한 매칭: 각 후보작의 'overview'(줄거리)와 'keywords'(키워드)를 사용자의 선호 테마와 정밀 대조하여 가장 완벽하게 공명하는 영화 딱 40편을 후보 목록에서 엄선하세요.{ott_prompt}

        [추천 후보 목록]
        {json.dumps(candidate_info, ensure_ascii=False)}

        [엄격한 출력 조건]
        1. 당신의 분석 과정이나 부연 설명은 절대 출력하지 마세요. (분석은 속으로만 진행하세요)
        2. 반드시 제공된 [추천 후보 목록] 안에서만 고르세요.
        3. 오직 선택된 영화의 "id" 숫자만 담은 순수 JSON 배열(List) 형식으로만 출력하세요.
        출력 예시: [12, 45, 88, 3, 21, 9, ...]
        """

        print("  🤖 [AI] 데이터 추출 완료, Gemini 딥러닝 통신 시작!")
        rate_limit_key = f"gemini_rate_limited_{user.id}"
        if cache.get(rate_limit_key):
            print("  ⚠️ [AI 방어막 작동] 최근 한도 초과 이력이 있어 구글 통신을 생략하고 즉시 예비 목록을 가동합니다.")
            raise Exception("Rate limit guard active (429 Bypass)")

        response = client.models.generate_content(
            model='models/gemini-2.5-flash', contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0),
        )

        # ==========================================================================
        # [PHASE 5: AI 응답 데이터 파싱 & 40개 확정 리스트 규칙 검증]
        # ==========================================================================
        text = response.text.replace('```json', '').replace('```', '').strip()
        raw_json = json.loads(text)
        parsed_ids = raw_json if isinstance(raw_json, list) else (next((v for v in raw_json.values() if isinstance(v, list)), []))
        recommended_ids = [int(_id) for _id in parsed_ids if str(_id).isdigit()]
        
        ai_selected_movies = [m for m in combined_candidates if m.id in recommended_ids]
        ai_selected_movies.sort(key=lambda x: x.imdb_vote_count or 0, reverse=True)
        
        kr_selected = [m for m in ai_selected_movies if '한국' in str(m.tmdb_production_country_kr)]
        jp_selected = [m for m in ai_selected_movies if '일본' in str(m.tmdb_production_country_kr) and '애니메이션' not in str(m.tmdb_genre)]
        
        final_40 = []
        no_ott_count = 0
        def add_to_final(movie):
            nonlocal no_ott_count
            if any(fm.id == movie.id for fm in final_40): return False
            if not movie.tmdb_streaming_providers:
                if no_ott_count >= 13: return False
                no_ott_count += 1
            final_40.append(movie)
            return True

        for m in kr_pool:
            if len(kr_selected) >= 3: break
            if m not in kr_selected: kr_selected.append(m)
        for m in jp_pool:
            if len(jp_selected) >= 2: break
            if m not in jp_selected: jp_selected.append(m)

        for m in kr_selected + jp_selected: add_to_final(m)
        for m in ai_selected_movies:
            if len(final_40) >= 40: break
            add_to_final(m)
        if len(final_40) < 40:
            for m in others_pool + kr_pool + jp_pool:
                if len(final_40) >= 40: break
                add_to_final(m)
        if len(final_40) < 40:
            for m in kr_pool + jp_pool + others_pool:
                if len(final_40) >= 40: break
                if not any(fm.id == m.id for fm in final_40): final_40.append(m)

        cache.set(cache_key, [m.id for m in final_40], timeout=60 * 60 * 24)
        return random.sample(final_40, min(10, len(final_40)))

    except Exception as e:
        # ==========================================================================
        # [PHASE 6: 플랜 B - 통신 에러 또는 API 한도 초과 시 비상 가동 로직]
        # ==========================================================================
        print(f"🚨 제미나이 AI 영화 에러 발동 (플랜 B 가동): {e}")
        try: 
            rate_limit_key = f"gemini_rate_limited_{user.id}"
            cache.set(rate_limit_key, True, timeout=300) 
        except: pass

        # 💡 1. 찜(Watchlist)은 제외하지 않고 오직 "평가한(Rating)" 작품만 제외하도록 수정! (찜한 건 추천에 떠야죠!)
        seen_ids = set(Rating.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True)) if user else set()
        
        # 💡 2. 보지 않은 영화들 중에서 줄거리/키워드가 있는 영화만 깨끗하게 필터링
        pool_unseen = base_pool.exclude(id__in=seen_ids).exclude(
            Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | 
            Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
        ).filter(Q(tmdb_title__regex=r'[가-힣]') | Q(tmdb_production_country_kr__icontains='한국'))
        
        # 💡 3. 상위권 풀을 넉넉히 가져와서 그 안에서 무작위로 섞어 뽑아냅니다!
        kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:40])
        jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:40])
        
        # 이미 뽑힌 한국/일본 영화는 제외하고 나머지 150개 추출
        exclude_ids = [m.id for m in kr_candidates + jp_candidates]
        others_candidates = list(pool_unseen.exclude(id__in=exclude_ids).order_by('-imdb_vote_count')[:150])

        # 🚀 [핵심 해결] 4. 안전하게 40개 조합하기
        fallback_40 = []
        fallback_40.extend(random.sample(kr_candidates, min(5, len(kr_candidates))))
        fallback_40.extend(random.sample(jp_candidates, min(3, len(jp_candidates))))
        
        # 남은 자리를 others_candidates로 꽉 채움 (총 40개가 되도록)
        remaining_needed = 40 - len(fallback_40)
        fallback_40.extend(random.sample(others_candidates, min(remaining_needed, len(others_candidates))))
        
        try: 
            cache_key = f"gemini_recs_v5_{user.id}" 
            fallback_40_ids = [m.id for m in fallback_40]
            cache.set(cache_key, fallback_40_ids, timeout=86400)
        except: pass
        
        # 40개 중에서 10개만 무작위로 화면에 던져줍니다.
        return random.sample(fallback_40, min(10, len(fallback_40)))


# 💡 [초보자 안내] 위 로직과 동일하지만 'TV 시리즈' 전용으로 동작하는 AI 추천 함수입니다.
def get_gemini_tv_recommendations(user, base_pool):
    try:
        from google.genai import Client
        from google.genai import types

        # ==========================================================================
        # [PHASE 1: 캐시 및 사용자가 이미 본(평가/찜) 영화 데이터 필터링]
        # ==========================================================================        
        cache_key = f"gemini_tv_recs_v5_{user.id}"
        cached_pool_ids = cache.get(cache_key)
        
        # 💡 [버그 픽스 유지] TV 시리즈만 정확히 필터링
        rated_ids = set(Rating.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True))
        watchlisted_ids = set(Watchlist.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True))
        seen_ids = rated_ids | watchlisted_ids

        if cached_pool_ids and len(cached_pool_ids) > 10:
            interacted_count = sum(1 for mid in cached_pool_ids if mid in rated_ids)
            if interacted_count < 10:
                unseen_ids = [mid for mid in cached_pool_ids if mid not in seen_ids]
                if len(unseen_ids) >= 10:
                    print(f"  ✅ [TV 캐시 적중] {len(unseen_ids)}개의 남은 풀에서 10개를 무작위 추출합니다!")
                    display_ids = random.sample(unseen_ids, 10)
                    series_dict = {m.id: m for m in TvSeries.objects.filter(id__in=display_ids)}
                    return [series_dict[mid] for mid in display_ids if mid in series_dict]
            else:
                print("  🔄 [TV AI] TV 시리즈 10개 평가 완료! 취향 변화를 반영하여 영화도 함께 재가동합니다...")
                cache.delete(f"gemini_recs_v5_{user.id}")
                cache.delete(f"gemini_fallback_v7_{user.id}")

        print("  🤖 [TV AI] Gemini 고차원 심층 분석 로직 진입...")
        client = Client(api_key=settings.GEMINI_API_KEY)

        # ==========================================================================
        # [PHASE 2: 사용자 취향 영화 분석 & 동일 조건 TV 시리즈 동시 추출]
        # ==========================================================================
        # 💡 [버그 픽스 유지] tvseries로 조회
        high_ratings = list(Rating.objects.filter(user=user, score__gte=8, tvseries__isnull=False).select_related('tvseries')[:50])
        if not high_ratings: 
            high_ratings = list(Rating.objects.filter(user=user, score__gte=6, tvseries__isnull=False).select_related('tvseries')[:50])
        if not high_ratings: return []

        tv_eval_count = len(high_ratings)
        favorite_movie_info = []
        if tv_eval_count > 0:
            fav_genres = [g.strip() for r in high_ratings for g in get_display_genre(r.tvseries.tmdb_genre, r.tvseries.imdb_genre).split(',') if g.strip() and g.strip() != '정보 없음']
            top_genre_names = [g for g, c in Counter(fav_genres).most_common(3)]
            movie_query = Movie.objects.exclude(Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')).filter(imdb_rating__gte=7.5)
            if top_genre_names:
                m_genre_q = Q()
                for g in top_genre_names: m_genre_q |= Q(tmdb_genre__icontains=g) | Q(imdb_genre__icontains=g)
                movie_query = movie_query.filter(m_genre_q)
            matched_movies = list(movie_query.order_by('-imdb_vote_count')[:tv_eval_count])
            favorite_movie_info = [
                f"'{m.tmdb_title}' (영화, {get_display_date(m.tmdb_release_date, m.imdb_release_date)[:4]}년, 국가: {m.tmdb_production_country_kr}, 장르: {get_display_genre(m.tmdb_genre, m.imdb_genre)}, 줄거리: {str(m.tmdb_overview)[:60]}..., 키워드: {str(m.tmdb_keywords)[:40]})" 
                for m in matched_movies
            ]

        ott_list = []
        for r in high_ratings:
            if r.tvseries.tmdb_streaming_providers:
                for prov in r.tvseries.tmdb_streaming_providers: ott_list.append(prov.get('provider_name'))

        top_otts = [ott for ott, count in Counter(ott_list).most_common(2)]
        ott_prompt = ""
        if top_otts:
            ott_prompt = f"\n        4. 스트리밍 최적화: 사용자는 주로 [{', '.join(top_otts)}] 플랫폼을 이용합니다. 제공된 [추천 후보 목록]의 'ott' 필드를 확인하여, 가급적 해당 플랫폼에서 시청 가능한 시리즈에 가산점을 부여하세요."

        favorite_info = [
            f"'{r.tvseries.tmdb_title}' ({get_display_date(r.tvseries.tmdb_release_date, r.tvseries.imdb_release_date)[:4]}년, 국가: {r.tvseries.tmdb_production_country_kr}, 장르: {get_display_genre(r.tvseries.tmdb_genre, r.tvseries.imdb_genre)}, 줄거리: {str(r.tvseries.tmdb_overview)[:80]}..., 키워드: {str(r.tvseries.tmdb_keywords)[:50]}, 내 평점: {r.score}/10점)" 
            for r in high_ratings
        ]

        # ==========================================================================
        # [PHASE 3: AI에게 제시할 추천 후보 목록(풀) 60개 엄선]
        # ==========================================================================
        valid_pool = base_pool.exclude(id__in=seen_ids).exclude(
            Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | 
            Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
        ).filter(Q(tmdb_title__regex=r'[가-힣]') | Q(tmdb_production_country_kr__icontains='한국'))

        kr_candidates = list(valid_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:50])
        jp_candidates = list(valid_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:50])
        kr_pool = random.sample(kr_candidates, min(10, len(kr_candidates)))
        jp_pool = random.sample(jp_candidates, min(10, len(jp_candidates)))
        
        exclude_ids = [m.id for m in kr_pool + jp_pool]
        others_candidates = list(valid_pool.exclude(id__in=exclude_ids).order_by('-imdb_vote_count')[:150])
        others_pool = random.sample(others_candidates, min(40, len(others_candidates)))

        combined_candidates = kr_pool + jp_pool + others_pool
        if not combined_candidates: return []

        candidate_info = [{
            "id": m.id, "title": m.tmdb_title if re.search(r'[가-힣]', str(m.tmdb_title or '')) else getattr(m, 'translated_title', m.tmdb_title), 
            "year": get_display_date(m.tmdb_release_date, m.imdb_release_date)[:4],
            "country": str(m.tmdb_production_country_kr or '정보 없음'), "genre": get_display_genre(m.tmdb_genre, m.imdb_genre),
            "overview": str(m.tmdb_overview)[:150], "keywords": str(m.tmdb_keywords)[:80],
            "ott": ", ".join([p.get('provider_name') for p in m.tmdb_streaming_providers]) if m.tmdb_streaming_providers else "정보 없음"
        } for m in combined_candidates]

        # ==========================================================================
        # [PHASE 4: 구글 제미나이(Gemini) AI 프롬프트 구성 및 통신 요청]
        # ==========================================================================
        # 💡 [정교한 원본 프롬프트 완벽 복구 - TV 시리즈 맞춤형]
        prompt = f"""
        당신은 세계 최고 수준의 평론가이자 맞춤형 AI 큐레이터입니다.
        단순히 텍스트로 주어진 장르나 국가를 매칭하는 수준을 넘어서, 당신이 가진 방대한 '데이터베이스(사전 학습된 지식)'를 총동원하여 고차원적인 분석을 수행하세요.

        [분석 대상 1: 사용자가 좋아하는 상위 TV 시리즈 목록]
        {', '.join(favorite_info)}

        [분석 대상 2: 사용자 취향 조건과 일치하는 상위 영화 목록 (서사 취향 참고용)]
        {', '.join(favorite_movie_info)}

        [분석 지시사항]
        1. 심층 취향 프로파일링: 위 TV 시리즈 및 영화 목록을 보고 이 사용자가 선호하는 작품의 '핵심 테마', '분위기(Mood)', '서사 구조', '선호하는 연출 스타일' 등을 심층적으로 유추하세요.
        2. 후보군 지식 활성화: 아래 [추천 후보 목록]에 있는 시리즈들의 실제 줄거리, 톤앤매너, 작품성을 당신의 지식 안에서 떠올리세요.
        3. 완벽한 매칭: 각 후보작의 'overview'(줄거리)와 'keywords'(키워드)를 사용자의 선호 테마와 정밀 대조하여 가장 완벽하게 공명하는 시리즈 딱 40편을 후보 목록에서 엄선하세요.{ott_prompt}

        [추천 후보 목록]
        {json.dumps(candidate_info, ensure_ascii=False)}

        [엄격한 출력 조건]
        1. 당신의 분석 과정이나 부연 설명은 절대 출력하지 마세요. (분석은 속으로만 진행하세요)
        2. 반드시 제공된 [추천 후보 목록] 안에서만 고르세요.
        3. 오직 선택된 시리즈의 "id" 숫자만 담은 순수 JSON 배열(List) 형식으로만 출력하세요.
        출력 예시: [12, 45, 88, 3, 21, 9, ...]
        """

        print("  🤖 [TV AI] 데이터 추출 완료, Gemini 딥러닝 통신 시작!")
        rate_limit_key = f"gemini_rate_limited_{user.id}"
        if cache.get(rate_limit_key):
            print("  ⚠️ [TV AI 방어막 작동] 최근 한도 초과 이력이 있어 구글 통신을 생략하고 즉시 예비 목록을 가동합니다.")
            raise Exception("Rate limit guard active")

        response = client.models.generate_content(
            model='models/gemini-2.5-flash', contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=1.0),
        )

        # ==========================================================================
        # [PHASE 5: AI 응답 데이터 파싱 & 40개 확정 리스트 규칙 검증]
        # ==========================================================================
        text = response.text.replace('```json', '').replace('```', '').strip()
        raw_json = json.loads(text)
        parsed_ids = raw_json if isinstance(raw_json, list) else (next((v for v in raw_json.values() if isinstance(v, list)), []))
        recommended_ids = [int(_id) for _id in parsed_ids if str(_id).isdigit()]
        
        ai_selected_series = [m for m in combined_candidates if m.id in recommended_ids]
        ai_selected_series.sort(key=lambda x: x.imdb_vote_count or 0, reverse=True)
        
        kr_selected = [m for m in ai_selected_series if '한국' in str(m.tmdb_production_country_kr)]
        jp_selected = [m for m in ai_selected_series if '일본' in str(m.tmdb_production_country_kr) and '애니메이션' not in str(m.tmdb_genre)]
        
        final_40 = []
        no_ott_count = 0
        def add_to_final(movie):
            nonlocal no_ott_count
            if any(fm.id == movie.id for fm in final_40): return False
            if not movie.tmdb_streaming_providers:
                if no_ott_count >= 13: return False
                no_ott_count += 1
            final_40.append(movie)
            return True

        for m in kr_pool:
            if len(kr_selected) >= 3: break
            if m not in kr_selected: kr_selected.append(m)
        for m in jp_pool:
            if len(jp_selected) >= 2: break
            if m not in jp_selected: jp_selected.append(m)

        for m in kr_selected + jp_selected: add_to_final(m)
        for m in ai_selected_series:
            if len(final_40) >= 40: break
            add_to_final(m)
        if len(final_40) < 40:
            for m in others_pool + kr_pool + jp_pool:
                if len(final_40) >= 40: break
                add_to_final(m)
        if len(final_40) < 40:
            for m in kr_pool + jp_pool + others_pool:
                if len(final_40) >= 40: break
                if not any(fm.id == m.id for fm in final_40): final_40.append(m)

        cache.set(cache_key, [m.id for m in final_40], timeout=60 * 60 * 24)
        return random.sample(final_40, min(10, len(final_40)))

    except Exception as e:
        # ==========================================================================
        # [PHASE 6: 플랜 B - 통신 에러 또는 API 한도 초과 시 비상 가동 로직]
        # ==========================================================================
        print(f"🚨 제미나이 AI TV 시리즈 에러 발동 (플랜 B 가동): {e}")
        try: 
            rate_limit_key = f"gemini_rate_limited_{user.id}"
            cache.set(rate_limit_key, True, timeout=300) 
        except: pass

        # 💡 1. 찜(Watchlist) 제외 삭제! "평가한(Rating)" 작품만 제외
        seen_ids = set(Rating.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True)) if user else set()
        
        pool_unseen = base_pool.exclude(id__in=seen_ids).exclude(
            Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | 
            Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
        ).filter(Q(tmdb_title__regex=r'[가-힣]') | Q(tmdb_production_country_kr__icontains='한국'))
        
        # 💡 3. 넉넉한 예비 풀 준비
        kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:40])
        jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:40])
        
        exclude_ids = [m.id for m in kr_candidates + jp_candidates]
        others_candidates = list(pool_unseen.exclude(id__in=exclude_ids).order_by('-imdb_vote_count')[:150])

        # 🚀 [핵심 해결] 4. 안전하게 40개 조합하기
        fallback_40 = []
        fallback_40.extend(random.sample(kr_candidates, min(5, len(kr_candidates))))
        fallback_40.extend(random.sample(jp_candidates, min(3, len(jp_candidates))))
        
        remaining_needed = 40 - len(fallback_40)
        fallback_40.extend(random.sample(others_candidates, min(remaining_needed, len(others_candidates))))
        
        try: 
            cache_key = f"gemini_tv_recs_v5_{user.id}" 
            fallback_40_ids = [m.id for m in fallback_40]
            cache.set(cache_key, fallback_40_ids, timeout=86400)
        except: pass
        
        return random.sample(fallback_40, min(10, len(fallback_40)))


# 💡 홈페이지에서 비동기로 영화 추천을 호출하는 API 뷰 (영화 전용)
def api_gemini_recommendations(request):
    user = request.user if request.user.is_authenticated else None
    eval_count = Rating.objects.filter(user=user, movie__isnull=False).count() if user else 0
    is_fallback = (eval_count < 10) if user else True

    search = request.GET.get('search', '')
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')
    is_filter_action = request.GET.get('filter_submitted') == 'true'

    if not is_filter_action and not request.GET.get('search') and not request.GET.get('sort'):
        exclude_doc, exclude_no_rating, exclude_low_votes, exclude_short, exclude_low_rating, exclude_unreleased, exclude_no_imdb = True, True, True, True, True, True, True
        # 💡 [의도된 UX 유지] 홈 화면에서 새로고침 시 평가한 작품은 눈앞에서 치워줍니다.
        exclude_rated = True 
    else:
        exclude_doc = request.GET.get('exclude_doc') == 'on'
        exclude_no_rating = request.GET.get('exclude_no_rating') == 'on'
        exclude_low_votes = request.GET.get('exclude_low_votes') == 'on'
        exclude_short = request.GET.get('exclude_short') == 'on'
        exclude_low_rating = request.GET.get('exclude_low_rating') == 'on'
        exclude_rated = request.GET.get('exclude_rated') == 'on'
        exclude_unreleased = request.GET.get('exclude_unreleased') == 'on'
        exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on'

    base_rec_pool = Movie.objects.exclude(imdb_rating__lt=6.5).exclude(
        Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
    ).filter(
        ( (Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본')) & Q(imdb_vote_count__gte=200) ) |
        ( (Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=5000) ) |
        ( ~(Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본') | Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=2000) )
    )

    cached_pool = []
    if user:
        if not is_fallback: cached_pool = get_gemini_recommendations(user, base_rec_pool)
        if not cached_pool or len(cached_pool) < 10:
            is_fallback = True
            fallback_cache_key = f"gemini_fallback_v7_{user.id}"
            fallback_ids = cache.get(fallback_cache_key)
            if fallback_ids:
                rated_ids = set(Rating.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True))
                if sum(1 for mid in fallback_ids if mid in rated_ids) >= 10:
                    cache.delete(fallback_cache_key)
                    cache.delete(f"gemini_tv_recs_v5_{user.id}")
                    cache.delete(f"gemini_tv_fallback_v7_{user.id}")
                    fallback_ids = None
            if fallback_ids: fallback_40 = list(Movie.objects.filter(id__in=fallback_ids))
            else:
                seen_ids = set(Rating.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True)) | set(Watchlist.objects.filter(user=user, movie__isnull=False).values_list('movie__id', flat=True))
                pool_unseen = base_rec_pool.exclude(id__in=seen_ids)
                kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:20])
                jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:20])
                others_candidates = list(pool_unseen.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:150])
                fallback_40 = random.sample(kr_candidates, min(3, len(kr_candidates))) + random.sample(jp_candidates, min(2, len(jp_candidates))) + random.sample(others_candidates, min(35, len(others_candidates)))
                cache.set(fallback_cache_key, [m.id for m in fallback_40], timeout=86400)
            cached_pool = fallback_40
    else:
        cache_key_anon = "gemini_rec_master_pool_anon_v7"
        cached_anon_ids = cache.get(cache_key_anon)
        if not cached_anon_ids:
            kr_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
            jp_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
            others_candidates = list(base_rec_pool.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
            fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
            cached_anon_ids = [m.id for m in fallback_40]
            cache.set(cache_key_anon, cached_anon_ids, timeout=86400)
        cached_pool = list(Movie.objects.filter(id__in=cached_anon_ids))

    filtered_pool = []
    today_str = str(timezone.now().date())

    for m in cached_pool:
        if search:
            search_low = search.lower()
            if (search_low not in (m.tmdb_title or '').lower() and 
                search_low not in (m.tmdb_original_title or '').lower() and 
                search_low not in getattr(m, 'translated_title', '').lower() and
                search_low not in (m.tmdb_actors or '').lower()):
                continue
        else:
            if exclude_no_imdb and (not m.tmdb_imdb_id or not str(m.tmdb_imdb_id).strip()): continue
            if exclude_doc:
                if m.tmdb_genre and '다큐' in m.tmdb_genre: continue
                if (not m.tmdb_genre or m.tmdb_genre == 'None') and m.imdb_genre and 'Documentary' in m.imdb_genre: continue
            if exclude_no_rating and m.imdb_rating == 0.0: continue
            if exclude_low_votes and (m.imdb_vote_count or 0) < 10: continue
            if exclude_short and 0 < get_display_runtime(m.tmdb_runtime, m.imdb_runtime) <= 60: continue  
            if exclude_low_rating and m.imdb_rating <= 4.0: continue
            if exclude_rated and user and Rating.objects.filter(user=user, movie=m).exists(): continue
            if exclude_unreleased:
                date_str = get_display_date(m.tmdb_release_date, m.imdb_release_date)
                if date_str != "----" and date_str[:4] > today_str[:4]: continue

            if selected_genres:
                g_str = get_display_genre(m.tmdb_genre, m.imdb_genre).lower()
                if not any(g.lower() in g_str for g in selected_genres): continue
            if selected_otts and not any(o.lower() in str(m.tmdb_streaming_providers or '').lower() for o in selected_otts): continue
            if selected_countries and not any(c.lower() == str(m.tmdb_production_country_kr or '').strip().lower() for c in selected_countries): continue
            if selected_ratings:
                kr = (m.tmdb_certification_kr or '').strip().upper()
                us = (m.tmdb_certification_us or '').strip().upper()
                final_rating = '정보 없음'
                if kr and kr not in ['정보 없음', '미등급']:
                    if kr == 'ALL': final_rating = 'ALL'
                    elif '18' in kr or '19' in kr: final_rating = '19'
                    elif '15' in kr: final_rating = '15'
                    elif '12' in kr: final_rating = '12'
                elif us and us not in ['정보 없음', '미등급', 'NR', 'UR', 'TBA']:
                    if us == 'G': final_rating = 'ALL'
                    elif us == 'PG-13': final_rating = '15'
                    elif us == 'PG': final_rating = '12'
                    elif us in ['R', 'NC-17']: final_rating = '19'
                if final_rating not in selected_ratings: continue

        filtered_pool.append(m)

    recommended_movies = random.sample(filtered_pool, min(len(filtered_pool), 10))

    if user and recommended_movies:
        rec_ids = [m.id for m in recommended_movies]
        rec_qs = Movie.objects.filter(id__in=rec_ids).annotate(my_score_db=Coalesce(Subquery(Rating.objects.filter(user=user, movie__id=OuterRef('pk')).values('score')), 0, output_field=IntegerField()))
        rec_map = {m.id: m for m in rec_qs}
        final_recommended = []
        for orig in recommended_movies:
            if orig.id in rec_map:
                m_obj = rec_map[orig.id]
                m_obj.my_score = m_obj.my_score_db
                final_recommended.append(m_obj)
            else:
                orig.my_score = 0
                final_recommended.append(orig)
        recommended_movies = final_recommended
    else:
        for m in recommended_movies: m.my_score = 0

    for m in recommended_movies:
        if m.tmdb_title and re.search(r'[가-힣]', m.tmdb_title):
            if hasattr(m, 'translated_title') and m.translated_title:
                m.translated_title = ''
                m.save(update_fields=['translated_title'])
        m.display_genre = get_display_genre(m.tmdb_genre, m.imdb_genre)
        m.display_date = get_display_date(m.tmdb_release_date, m.imdb_release_date)
        m.display_runtime = get_display_runtime(m.tmdb_runtime, m.imdb_runtime)
        g_val = m.display_genre
        m.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)
        c_val = str(m.tmdb_production_country_kr or '')
        m.short_country = c_val.split(',')[0].strip() + "+" if ',' in c_val else c_val

    html = render_to_string('partials/comp_recommend_row.html', {
        'recommended_movies': recommended_movies,
        'is_anonymous': not user,
        'is_fallback': is_fallback,
        'is_tv': False,
        'user': user,
    }, request=request)

    return JsonResponse({'html': html})

# 💡 홈페이지에서 비동기로 TV 시리즈 추천을 호출하는 API 뷰 (TV 시리즈 전용)
def api_gemini_tv_recommendations(request):
    user = request.user if request.user.is_authenticated else None
    eval_count = Rating.objects.filter(user=user, tvseries__isnull=False).count() if user else 0
    is_fallback = (eval_count < 10) if user else True

    search = request.GET.get('search', '')
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')
    is_filter_action = request.GET.get('filter_submitted') == 'true'

    if not is_filter_action and not request.GET.get('search') and not request.GET.get('sort'):
        exclude_doc, exclude_no_rating, exclude_low_votes, exclude_short, exclude_low_rating, exclude_unreleased, exclude_no_imdb = True, True, True, True, True, True, True
        # 💡 [의도된 UX 유지] 홈 화면에서 새로고침 시 평가한 작품은 눈앞에서 치워줍니다.
        exclude_rated = True 
    else:
        exclude_doc = request.GET.get('exclude_doc') == 'on'
        exclude_no_rating = request.GET.get('exclude_no_rating') == 'on'
        exclude_low_votes = request.GET.get('exclude_low_votes') == 'on'
        exclude_short = request.GET.get('exclude_short') == 'on'
        exclude_low_rating = request.GET.get('exclude_low_rating') == 'on'
        exclude_rated = request.GET.get('exclude_rated') == 'on'
        exclude_unreleased = request.GET.get('exclude_unreleased') == 'on'
        exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on'

    base_rec_pool = TvSeries.objects.exclude(imdb_rating__lt=6.5).exclude(
        Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')
    ).filter(
        ( (Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본')) & Q(imdb_vote_count__gte=100) ) |
        ( (Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=2000) ) |
        ( ~(Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본') | Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=500) )
    )

    cached_pool = []
    if user:
        if not is_fallback: cached_pool = get_gemini_tv_recommendations(user, base_rec_pool)
        if not cached_pool or len(cached_pool) < 10:
            is_fallback = True
            fallback_cache_key = f"gemini_tv_fallback_v7_{user.id}"
            fallback_ids = cache.get(fallback_cache_key)

            if fallback_ids:
                rated_ids = set(Rating.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True))
                if sum(1 for mid in fallback_ids if mid in rated_ids) >= 10:
                    cache.delete(fallback_cache_key)
                    cache.delete(f"gemini_recs_v5_{user.id}")
                    cache.delete(f"gemini_fallback_v7_{user.id}")
                    fallback_ids = None

            if fallback_ids: 
                fallback_40 = list(TvSeries.objects.filter(id__in=fallback_ids))
            else:
                seen_ids = set(Rating.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True)) | set(Watchlist.objects.filter(user=user, tvseries__isnull=False).values_list('tvseries__id', flat=True))
                pool_unseen = base_rec_pool.exclude(id__in=seen_ids)
                
                kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:20])
                jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:20])
                others_candidates = list(pool_unseen.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:150])
                
                fallback_40 = random.sample(kr_candidates, min(3, len(kr_candidates))) + \
                              random.sample(jp_candidates, min(2, len(jp_candidates))) + \
                              random.sample(others_candidates, min(35, len(others_candidates)))
                
                cache.set(fallback_cache_key, [m.id for m in fallback_40], timeout=86400)
                
            cached_pool = fallback_40
    else:
        cache_key_anon = "gemini_tv_rec_master_pool_anon_v7"
        cached_anon_ids = cache.get(cache_key_anon)
        if not cached_anon_ids:
            kr_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
            jp_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
            others_candidates = list(base_rec_pool.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
            fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
            cached_anon_ids = [m.id for m in fallback_40]
            cache.set(cache_key_anon, cached_anon_ids, timeout=86400)
        cached_pool = list(TvSeries.objects.filter(id__in=cached_anon_ids))

    filtered_pool = []
    today_str = str(timezone.now().date())

    for m in cached_pool:
        if search:
            search_low = search.lower()
            if (search_low not in (m.tmdb_title or '').lower() and 
                search_low not in (m.tmdb_original_title or '').lower() and 
                search_low not in getattr(m, 'translated_title', '').lower() and
                search_low not in (m.tmdb_actors or '').lower()):
                continue
        else:
            if exclude_no_imdb and (not m.tmdb_imdb_id or not str(m.tmdb_imdb_id).strip()): continue
            if exclude_doc:
                if m.tmdb_genre and '다큐' in m.tmdb_genre: continue
                if (not m.tmdb_genre or m.tmdb_genre == 'None') and m.imdb_genre and 'Documentary' in m.imdb_genre: continue
            if exclude_no_rating and m.imdb_rating == 0.0: continue
            if exclude_low_votes and (m.imdb_vote_count or 0) < 10: continue
            if exclude_short and 0 < get_display_runtime(m.tmdb_runtime, m.imdb_runtime) <= 20: continue  
            if exclude_low_rating and m.imdb_rating <= 4.0: continue
            if exclude_rated and user and Rating.objects.filter(user=user, tvseries=m).exists(): continue
            if exclude_unreleased:
                date_str = get_display_date(m.tmdb_release_date, m.imdb_release_date)
                if date_str != "----" and date_str[:4] > today_str[:4]: continue

            if selected_genres:
                g_str = get_display_genre(m.tmdb_genre, m.imdb_genre).lower()
                if not any(g.lower() in g_str for g in selected_genres): continue
            if selected_otts and not any(o.lower() in str(m.tmdb_streaming_providers or '').lower() for o in selected_otts): continue
            if selected_countries and not any(c.lower() == str(m.tmdb_production_country_kr or '').strip().lower() for c in selected_countries): continue
            if selected_ratings:
                kr = (m.tmdb_certification_kr or '').strip().upper()
                us = (m.tmdb_certification_us or '').strip().upper()
                final_rating = '정보 없음'
                if kr and kr not in ['정보 없음', '미등급']:
                    if kr == 'ALL': final_rating = 'ALL'
                    elif '18' in kr or '19' in kr: final_rating = '19'
                    elif '15' in kr: final_rating = '15'
                    elif '12' in kr: final_rating = '12'
                elif us and us not in ['정보 없음', '미등급', 'NR', 'UR', 'TBA']:
                    if us == 'G': final_rating = 'ALL'
                    elif us == 'PG-13': final_rating = '15'
                    elif us == 'PG': final_rating = '12'
                    elif us in ['R', 'NC-17', 'TV-MA']: final_rating = '19'
                if final_rating not in selected_ratings: continue

        filtered_pool.append(m)

    recommended_series = random.sample(filtered_pool, min(len(filtered_pool), 10))
    
    if user and recommended_series:
        rec_ids = [m.id for m in recommended_series]
        rec_qs = TvSeries.objects.filter(id__in=rec_ids).annotate(my_score_db=Coalesce(Subquery(Rating.objects.filter(user=user, tvseries__id=OuterRef('pk')).values('score')), 0, output_field=IntegerField()))
        rec_map = {m.id: m for m in rec_qs}
        final_recommended = []
        for orig in recommended_series:
            if orig.id in rec_map:
                m_obj = rec_map[orig.id]
                m_obj.my_score = m_obj.my_score_db
                final_recommended.append(m_obj)
            else:
                orig.my_score = 0
                final_recommended.append(orig)
        recommended_series = final_recommended
    else:
        for m in recommended_series: m.my_score = 0

    for m in recommended_series:
        if m.tmdb_title and re.search(r'[가-힣]', m.tmdb_title):
            if hasattr(m, 'translated_title') and m.translated_title:
                m.translated_title = ''
                m.save(update_fields=['translated_title'])
        m.display_genre = get_display_genre(m.tmdb_genre, m.imdb_genre)
        m.display_date = get_display_date(m.tmdb_release_date, m.imdb_release_date)
        m.display_runtime = get_display_runtime(m.tmdb_runtime, m.imdb_runtime)
        g_val = m.display_genre
        m.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)
        c_val = str(m.tmdb_production_country_kr or '')
        m.short_country = c_val.split(',')[0].strip() + "+" if ',' in c_val else c_val

    html = render_to_string('partials/comp_recommend_row.html', {
        'recommended_movies': recommended_series,
        'is_anonymous': not user,
        'is_fallback': is_fallback,
        'is_tv': True,
        'user': user,
    }, request=request)

    return JsonResponse({'html': html})



# ==============================================================================
# [SECTION 5] 메인 목록 뷰 (Home, All List, Rec More Views)
# ==============================================================================
# 💡 [초보자 안내] 홈페이지 메인 화면을 구성하는 뷰입니다.
def home(request):
    user = request.user if request.user.is_authenticated else None
    eval_count = Rating.objects.filter(user=user).count() if user else 0
    is_fallback = (eval_count < 10) if user else True

    search = request.GET.get('search', '')
    sort = request.GET.get('sort', '')
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')
    per_page = request.GET.get('per_page', '15')
    is_filter_action = request.GET.get('filter_submitted') == 'true'

    if not is_filter_action and not request.GET.get('page') and not request.GET.get('search') and not request.GET.get('sort'):
        exclude_doc, exclude_no_rating, exclude_low_votes, exclude_short, exclude_low_rating, exclude_rated, exclude_unreleased, exclude_no_imdb = True, True, True, True, True, True, True, True
    else:
        exclude_doc = request.GET.get('exclude_doc') == 'on'
        exclude_no_rating = request.GET.get('exclude_no_rating') == 'on'
        exclude_low_votes = request.GET.get('exclude_low_votes') == 'on'
        exclude_short = request.GET.get('exclude_short') == 'on'
        exclude_low_rating = request.GET.get('exclude_low_rating') == 'on'
        exclude_rated = request.GET.get('exclude_rated') == 'on'
        exclude_unreleased = request.GET.get('exclude_unreleased') == 'on'
        exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on'

    # 💡 [절대 방어] 아예 시작부터 IMDb ID가 없는 불량품은 덜어내고 시작합니다!
    common_movies = Movie.objects.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))

    # 💡 [핵심 해결] 검색어가 존재할 경우, 모든 제외 필터 및 선택 필터를 우회하여 원제와 번역제목, 배우명까지 스캔!
    if search:
        q_cond = Q(tmdb_title__icontains=search)
        if hasattr(common_movies.model, 'tmdb_original_title'): q_cond |= Q(tmdb_original_title__icontains=search)
        if hasattr(common_movies.model, 'translated_title'): q_cond |= Q(translated_title__icontains=search)
        if hasattr(common_movies.model, 'tmdb_actors'): q_cond |= Q(tmdb_actors__icontains=search)
        common_movies = common_movies.filter(q_cond)

    if not search:
        if exclude_no_imdb: common_movies = common_movies.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))
        if exclude_doc: common_movies = common_movies.exclude(Q(tmdb_genre__icontains='다큐') | Q(Q(tmdb_genre='') | Q(tmdb_genre__isnull=True), imdb_genre__icontains='Documentary'))
        if exclude_no_rating: common_movies = common_movies.exclude(imdb_rating=0.0)
        if exclude_low_votes: common_movies = common_movies.filter(imdb_vote_count__gte=100)
        if exclude_short: common_movies = common_movies.exclude(Q(tmdb_runtime__gt=0, tmdb_runtime__lte=60) | Q(Q(tmdb_runtime=0) | Q(tmdb_runtime__isnull=True), imdb_runtime__gt=0, imdb_runtime__lte=60))
        if exclude_low_rating: common_movies = common_movies.exclude(imdb_rating__lt=5.0)
        if exclude_rated and user: common_movies = common_movies.exclude(id__in=Rating.objects.filter(user=user, movie__isnull=False).values('movie__id'))
        if exclude_unreleased:
            today_date = timezone.now().date()
            common_movies = common_movies.exclude(Q(tmdb_release_date__gt=today_date) | Q(tmdb_release_date__isnull=True, imdb_release_date__gt=str(today_date.year)))

        if selected_ratings:
            rating_q = Q()
            for rating in selected_ratings:
                if rating == 'ALL': rating_q |= (Q(tmdb_certification_kr__in=['ALL', 'All']) | Q(tmdb_certification_kr__icontains='전체') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='G')))
                elif rating == '12': rating_q |= (Q(tmdb_certification_kr__icontains='12') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='PG')))
                elif rating == '15': rating_q |= (Q(tmdb_certification_kr__icontains='15') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='PG-13')))
                elif rating == '19': rating_q |= (Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us__in=['R', 'NC-17'])))
                elif rating == '정보 없음': rating_q |= (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us__in=['', '정보 없음', '미등급', 'NR', 'UR', 'TBA']))
            common_movies = common_movies.filter(rating_q)

    country_queries = Q()
    if selected_countries:
        for c in selected_countries:
            if c == '정보 없음': country_queries |= (Q(tmdb_production_country_kr__isnull=True) | Q(tmdb_production_country_kr='') | Q(tmdb_production_country_kr='None'))
            else: country_queries |= Q(tmdb_production_country_kr=c)

    genre_queries = Q()
    if selected_genres:
        for genre in selected_genres:
            if genre == '정보 없음': genre_queries |= (Q(tmdb_genre__isnull=True) | Q(tmdb_genre='') | Q(tmdb_genre='None')) & (Q(imdb_genre__isnull=True) | Q(imdb_genre='') | Q(imdb_genre='None'))
            else:
                q = Q(tmdb_genre__icontains=genre)
                for en_g, kr_g in IMDB_GENRE_MAP.items():
                    if kr_g == genre: q |= Q(imdb_genre__icontains=en_g)
                genre_queries |= q

    ott_queries = Q()
    if selected_otts:
        for ott in selected_otts: ott_queries |= Q(tmdb_streaming_providers__icontains=ott)

    genre_base = common_movies
    if not search:
        if selected_countries: genre_base = genre_base.filter(country_queries)
        if selected_otts: genre_base = genre_base.filter(ott_queries)
    genres_list = get_all_genres(genre_base)

    ott_base = common_movies
    if not search:
        if selected_countries: ott_base = ott_base.filter(country_queries)
        if selected_genres: ott_base = ott_base.filter(genre_queries)
    otts_list = get_ott_list_with_logos(ott_base)

    country_base = common_movies
    if not search:
        if selected_genres: country_base = country_base.filter(genre_queries)
        if selected_otts: country_base = country_base.filter(ott_queries)
        
    # 💡 5만개 스캔 방지: 인기 국가 강제 고정
    # 💡 국기 이모지가 포함된 국가 리스트 (id: DB조회용, name: 화면표시용)
    # 💡 윈도우에서도 절대 안 깨지는 고화질 국기 이미지 적용 
    countries_list = [
        {'id': '한국', 'name': '한국', 'flag': 'https://flagcdn.com/w40/kr.png'},
        {'id': '미국', 'name': '미국', 'flag': 'https://flagcdn.com/w40/us.png'},
        {'id': '영국', 'name': '영국', 'flag': 'https://flagcdn.com/w40/gb.png'},
        {'id': '일본', 'name': '일본', 'flag': 'https://flagcdn.com/w40/jp.png'},
        {'id': '중국', 'name': '중국', 'flag': 'https://flagcdn.com/w40/cn.png'},
        {'id': '홍콩', 'name': '홍콩', 'flag': 'https://flagcdn.com/w40/hk.png'},
        {'id': '인도', 'name': '인도', 'flag': 'https://flagcdn.com/w40/in.png'},
        {'id': '프랑스', 'name': '프랑스', 'flag': 'https://flagcdn.com/w40/fr.png'},
        {'id': '캐나다', 'name': '캐나다', 'flag': 'https://flagcdn.com/w40/ca.png'},
        {'id': '독일', 'name': '독일', 'flag': 'https://flagcdn.com/w40/de.png'},
        {'id': '스페인', 'name': '스페인', 'flag': 'https://flagcdn.com/w40/es.png'},
        {'id': '벨기에', 'name': '벨기에', 'flag': 'https://flagcdn.com/w40/be.png'},
        {'id': '호주', 'name': '호주', 'flag': 'https://flagcdn.com/w40/au.png'},
        {'id': '이탈리아', 'name': '이탈리아', 'flag': 'https://flagcdn.com/w40/it.png'},
        {'id': '스웨덴', 'name': '스웨덴', 'flag': 'https://flagcdn.com/w40/se.png'},
        {'id': '아일랜드', 'name': '아일랜드', 'flag': 'https://flagcdn.com/w40/ie.png'},
        {'id': '터키', 'name': '터키', 'flag': 'https://flagcdn.com/w40/tr.png'},
        {'id': '덴마크', 'name': '덴마크', 'flag': 'https://flagcdn.com/w40/dk.png'},
        {'id': '스위스', 'name': '스위스', 'flag': 'https://flagcdn.com/w40/ch.png'},
        {'id': '노르웨이', 'name': '노르웨이', 'flag': 'https://flagcdn.com/w40/no.png'},
#        {'id': '정보 없음', 'name': '정보 없음', 'flag': 'https://www.google.com/s2/favicons?domain=wikipedia.org&sz=128'}
    ]

    base_rec_pool = common_movies
    if not search:
        if selected_countries: base_rec_pool = base_rec_pool.filter(country_queries)
        if selected_genres: base_rec_pool = base_rec_pool.filter(genre_queries)
        if selected_otts: base_rec_pool = base_rec_pool.filter(ott_queries)

    movies = base_rec_pool
    if user:
        user_rating_subquery = Rating.objects.filter(user=user, movie__id=OuterRef('pk')).values('score')
        movies = movies.annotate(my_score_db=Coalesce(Subquery(user_rating_subquery), 0, output_field=IntegerField()))
    else:
        movies = movies.annotate(my_score_db=Value(0, output_field=IntegerField()))

    if sort == 'imdb_desc': movies = movies.order_by('-imdb_rating', '-id')
    elif sort == 'imdb_asc': movies = movies.order_by('imdb_rating', 'id')
    elif sort == 'my_desc': movies = movies.order_by('-my_score_db', '-imdb_rating', '-id')
    elif sort == 'my_asc': movies = movies.annotate(has_score=Case(When(my_score_db__gt=0, then=Value(1)), default=Value(0), output_field=IntegerField())).order_by('-has_score', 'my_score_db', 'imdb_rating')
    elif sort == 'votes_desc': movies = movies.order_by('-imdb_vote_count', '-id')
    elif sort == 'votes_asc': movies = movies.order_by('imdb_vote_count', 'id')
    else: movies = movies.order_by('-imdb_vote_count', '-id')

    try:
        per_page_int = int(per_page)
        if per_page_int not in [15, 30, 60]: per_page_int = 30
    except (ValueError, TypeError): per_page_int = 30

    paginator = Paginator(movies, per_page_int) 
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    for movie in page_obj.object_list:
        movie.my_score = movie.my_score_db
        if movie.tmdb_title and re.search(r'[가-힣]', movie.tmdb_title):
            if movie.translated_title:
                movie.translated_title = ''
                movie.save(update_fields=['translated_title'])
        movie.display_genre = get_display_genre(movie.tmdb_genre, movie.imdb_genre)
        movie.display_date = get_display_date(movie.tmdb_release_date, movie.imdb_release_date)
        movie.display_runtime = get_display_runtime(movie.tmdb_runtime, movie.imdb_runtime)
        g_val = movie.display_genre
        movie.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)
        c_val = str(movie.tmdb_production_country_kr or '')
        movie.short_country = c_val.split(',')[0].strip() + "+" if ',' in c_val else c_val

    # 💡 히어로 배너용 영화 추출 로직 (한글 제목 필수)
    hero_movie = None
    if not is_filter_action and not search and not sort:
        six_months_ago = timezone.now().date() - timedelta(days=180)
        recent_top_movies = list(Movie.objects.filter(tmdb_release_date__gte=six_months_ago, tmdb_release_date__lte=timezone.now().date(), imdb_vote_count__gte=100, tmdb_title__regex=r'[가-힣]').order_by('-imdb_vote_count')[:10])
        if not recent_top_movies:
            two_years_ago = timezone.now().date() - timedelta(days=730)
            recent_top_movies = list(Movie.objects.filter(tmdb_release_date__gte=two_years_ago, tmdb_release_date__lte=timezone.now().date(), imdb_vote_count__gte=100, tmdb_title__regex=r'[가-힣]').order_by('-imdb_vote_count')[:10])
        if not recent_top_movies:
            latest_movies = Movie.objects.filter(tmdb_title__regex=r'[가-힣]').exclude(tmdb_release_date__isnull=True).order_by('-tmdb_release_date')[:50]
            recent_top_movies = sorted(latest_movies, key=lambda x: x.imdb_vote_count or 0, reverse=True)[:10]

        if recent_top_movies:
            hero_movie = random.choice(recent_top_movies)
            hero_movie.display_date = get_display_date(hero_movie.tmdb_release_date, hero_movie.imdb_release_date)
            g_val = get_display_genre(hero_movie.tmdb_genre, hero_movie.imdb_genre)
            hero_movie.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)

    return render(request, 'movie/home.html', {
        'movies': page_obj,  
        'recommended_movies': [], 
        'sort_by': sort, 'search_query': search,
        'genres_list': genres_list, 'selected_genres': selected_genres,
        'otts_list': otts_list, 'selected_otts': selected_otts,
        'countries_list': countries_list, 'selected_countries': selected_countries, 
        'selected_ratings': selected_ratings,     
        'exclude_doc': exclude_doc, 'exclude_no_rating': exclude_no_rating, 'exclude_low_votes': exclude_low_votes,
        'exclude_short': exclude_short, 'exclude_low_rating': exclude_low_rating, 'exclude_rated': exclude_rated,
        'exclude_unreleased': exclude_unreleased, 'exclude_no_imdb': exclude_no_imdb,
        'filter_submitted': 'true' if is_filter_action else '',
        'per_page': str(per_page_int), 'hero_movie': hero_movie, 'is_fallback': is_fallback 
    })

# 💡 [초보자 안내] 맞춤 AI 영화 추천 전체 보기 페이지 (기본 10편보다 많은 전체 리스트 40편 제공)
def rec_more_movies_view(request):
    user = request.user if request.user.is_authenticated else None

    # 🚀 프론트에서 강제 새로고침 신호(?force_refresh=true)가 오면 캐시 싹 비우기
    if request.GET.get('force_refresh') == 'true' and user:
        cache.delete(f"gemini_recs_v5_{user.id}")
        cache.delete(f"gemini_fallback_v7_{user.id}")
        cache.delete(f"gemini_tv_recs_v5_{user.id}")
        cache.delete(f"gemini_tv_fallback_v7_{user.id}")
        # 💡 [핵심] 쿼리스트링을 떼어내고 깔끔한 주소로 리다이렉트하여 F5 새로고침 무한루프(API 과금) 방지!
        return redirect(request.path)

    eval_count = Rating.objects.filter(user=user, movie__isnull=False).count() if user else 0
    is_fallback = (eval_count < 10) if user else True

    search = request.GET.get('search', '')
    sort = request.GET.get('sort', '')
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')

    # 🚀 [핵심 수정] 처음 진입 시 exclude_rated(내가 평가한 작품 제외)는 꺼둠(False)!
    is_filter_action = request.GET.get('filter_submitted') == 'true'

    if not is_filter_action and not search and not sort:
        exclude_doc, exclude_no_rating, exclude_low_votes, exclude_short, exclude_low_rating, exclude_unreleased, exclude_no_imdb = True, True, True, True, True, True, True
        exclude_rated = False  # 💡 얘만 쏙 빼서 끕니다!
    else:
        exclude_doc = request.GET.get('exclude_doc') == 'on'
        exclude_no_rating = request.GET.get('exclude_no_rating') == 'on'
        exclude_low_votes = request.GET.get('exclude_low_votes') == 'on'
        exclude_short = request.GET.get('exclude_short') == 'on'
        exclude_low_rating = request.GET.get('exclude_low_rating') == 'on'
        exclude_rated = request.GET.get('exclude_rated') == 'on'
        exclude_unreleased = request.GET.get('exclude_unreleased') == 'on'
        exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on'

    base_rec_pool = Movie.objects.exclude(imdb_rating__lt=6.5).exclude(Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')).filter(( (Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본')) & Q(imdb_vote_count__gte=200) ) | ( (Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=5000) ) | ( ~(Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본') | Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=2000) ))

    ai_movies_qs = Movie.objects.none()
    if user:
        cache_key = f"gemini_fallback_v7_{user.id}" if is_fallback else f"gemini_recs_v5_{user.id}"
        cached_ids = cache.get(cache_key)
        
        if cached_ids: # 💡 is_fallback 여부 상관없이 10개 평가면 무조건 폭파
            rated_ids = set(Rating.objects.filter(user=user).values_list('movie__id', flat=True))
            if sum(1 for mid in cached_ids if mid in rated_ids) >= 10:
                cache.delete(cache_key)
                cache.delete(f"gemini_tv_recs_v5_{user.id}")
                cache.delete(f"gemini_tv_fallback_v7_{user.id}")
                cached_ids = None

        if not cached_ids:
            if not is_fallback:
                get_gemini_recommendations(user, base_rec_pool)
                cached_ids = cache.get(cache_key, [])
            
            if not cached_ids or is_fallback:
                is_fallback = True
                cache_key = f"gemini_fallback_v7_{user.id}"
                rated_ids = set(Rating.objects.filter(user=user).values_list('movie__id', flat=True))
                watchlisted_ids = set(Watchlist.objects.filter(user=user).values_list('movie__id', flat=True))
                seen_ids = rated_ids | watchlisted_ids
                
                pool_unseen = base_rec_pool.exclude(id__in=seen_ids)
                kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
                jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
                others_candidates = list(pool_unseen.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
                
                fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
                cached_ids = [m.id for m in fallback_40]
                cache.set(cache_key, cached_ids, timeout=86400)

        ai_movies_qs = Movie.objects.filter(id__in=cached_ids)
        page_title = '🔥 기본 추천 영화 40편' if is_fallback else '✨ 맞춤형 AI 추천 [영화]'
        page_subtitle = '(10건 이상 평가하고 맞춤 AI 추천 받기)' if is_fallback else ''
    else:
        cache_key_anon = "gemini_rec_master_pool_anon_v7"
        cached_anon_ids = cache.get(cache_key_anon)
        if not cached_anon_ids:
            kr_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
            jp_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
            others_candidates = list(base_rec_pool.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
            fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
            cached_anon_ids = [m.id for m in fallback_40]
            cache.set(cache_key_anon, cached_anon_ids, timeout=86400)
            
        ai_movies_qs = Movie.objects.filter(id__in=cached_anon_ids)
        page_title = '🔥 오늘의 강력 추천 영화'
        page_subtitle = '(로그인하고 맞춤 AI 추천받기)'

    common_movies = ai_movies_qs

    # 💡 [핵심] 검색어가 존재할 경우, 모든 제외/선택 필터를 무시하고 원제와 배우명까지 싹 다 스캔!
    if search:
        q_cond = Q(tmdb_title__icontains=search)
        if hasattr(common_movies.model, 'tmdb_original_title'): q_cond |= Q(tmdb_original_title__icontains=search)
        if hasattr(common_movies.model, 'translated_title'): q_cond |= Q(translated_title__icontains=search)
        if hasattr(common_movies.model, 'tmdb_actors'): q_cond |= Q(tmdb_actors__icontains=search)
        common_movies = common_movies.filter(q_cond)

    if not search:
        if exclude_no_imdb: common_movies = common_movies.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))
        if exclude_doc: common_movies = common_movies.exclude(Q(tmdb_genre__icontains='다큐') | Q(Q(tmdb_genre='') | Q(tmdb_genre__isnull=True), imdb_genre__icontains='Documentary'))
        if exclude_no_rating: common_movies = common_movies.exclude(imdb_rating=0.0)
        if exclude_low_votes: common_movies = common_movies.filter(imdb_vote_count__gte=10)
        if exclude_short: common_movies = common_movies.exclude(Q(tmdb_runtime__gt=0, tmdb_runtime__lte=60) | Q(Q(tmdb_runtime=0) | Q(tmdb_runtime__isnull=True), imdb_runtime__gt=0, imdb_runtime__lte=60))
        if exclude_low_rating: common_movies = common_movies.exclude(imdb_rating__lt=5.0)
        if exclude_rated and user: common_movies = common_movies.exclude(id__in=Rating.objects.filter(user=user, movie__isnull=False).values('movie__id'))
        if exclude_unreleased:
            today_date = timezone.now().date()
            common_movies = common_movies.exclude(Q(tmdb_release_date__gt=today_date) | Q(tmdb_release_date__isnull=True, imdb_release_date__gt=str(today_date.year)))

        if selected_ratings:
            rating_q = Q()
            for r_val in selected_ratings:
                if r_val == 'ALL': rating_q |= (Q(tmdb_certification_kr__in=['ALL', 'All']) | Q(tmdb_certification_kr__icontains='전체') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='G')))
                elif r_val == '12': rating_q |= (Q(tmdb_certification_kr__icontains='12') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='PG')))
                elif r_val == '15': rating_q |= (Q(tmdb_certification_kr__icontains='15') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us='PG-13')))
                elif r_val == '19': rating_q |= (Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us__in=['R', 'NC-17'])))
                elif r_val == '정보 없음': rating_q |= (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급']) & Q(tmdb_certification_us__in=['', '정보 없음', '미등급', 'NR', 'UR', 'TBA']))
            common_movies = common_movies.filter(rating_q)

    country_queries = Q()
    if selected_countries:
        for c in selected_countries:
            if c == '정보 없음': country_queries |= (Q(tmdb_production_country_kr__isnull=True) | Q(tmdb_production_country_kr='') | Q(tmdb_production_country_kr='None'))
            else: country_queries |= Q(tmdb_production_country_kr=c)

    genre_queries = Q()
    if selected_genres:
        for genre in selected_genres:
            if genre == '정보 없음': genre_queries |= (Q(tmdb_genre__isnull=True) | Q(tmdb_genre='') | Q(tmdb_genre='None')) & (Q(imdb_genre__isnull=True) | Q(imdb_genre='') | Q(imdb_genre='None'))
            else:
                q = Q(tmdb_genre__icontains=genre)
                for en_g, kr_g in IMDB_GENRE_MAP.items():
                    if kr_g == genre: q |= Q(imdb_genre__icontains=en_g)
                genre_queries |= q

    ott_queries = Q()
    if selected_otts:
        for ott in selected_otts: ott_queries |= Q(tmdb_streaming_providers__icontains=ott)

    genre_base = common_movies
    if not search:
        if selected_countries: genre_base = genre_base.filter(country_queries)
        if selected_otts: genre_base = genre_base.filter(ott_queries)
    genres_list = get_all_genres(genre_base)

    ott_base = common_movies
    if not search:
        if selected_countries: ott_base = ott_base.filter(country_queries)
        if selected_genres: ott_base = ott_base.filter(genre_queries)
    otts_list = get_ott_list_with_logos(ott_base)

    country_base = common_movies
    if not search:
        if selected_genres: country_base = country_base.filter(genre_queries)
        if selected_otts: country_base = country_base.filter(ott_queries)
    # 💡 5만개 스캔 방지: 인기 국가 강제 고정
    # 💡 국기 이모지가 포함된 국가 리스트 (id: DB조회용, name: 화면표시용)
    # 💡 윈도우에서도 절대 안 깨지는 고화질 국기 이미지 적용 
    countries_list = [
        {'id': '한국', 'name': '한국', 'flag': 'https://flagcdn.com/w40/kr.png'},
        {'id': '미국', 'name': '미국', 'flag': 'https://flagcdn.com/w40/us.png'},
        {'id': '영국', 'name': '영국', 'flag': 'https://flagcdn.com/w40/gb.png'},
        {'id': '일본', 'name': '일본', 'flag': 'https://flagcdn.com/w40/jp.png'},
        {'id': '중국', 'name': '중국', 'flag': 'https://flagcdn.com/w40/cn.png'},
        {'id': '홍콩', 'name': '홍콩', 'flag': 'https://flagcdn.com/w40/hk.png'},
        {'id': '인도', 'name': '인도', 'flag': 'https://flagcdn.com/w40/in.png'},
        {'id': '프랑스', 'name': '프랑스', 'flag': 'https://flagcdn.com/w40/fr.png'},
        {'id': '캐나다', 'name': '캐나다', 'flag': 'https://flagcdn.com/w40/ca.png'},
        {'id': '독일', 'name': '독일', 'flag': 'https://flagcdn.com/w40/de.png'},
        {'id': '스페인', 'name': '스페인', 'flag': 'https://flagcdn.com/w40/es.png'},
        {'id': '벨기에', 'name': '벨기에', 'flag': 'https://flagcdn.com/w40/be.png'},
        {'id': '호주', 'name': '호주', 'flag': 'https://flagcdn.com/w40/au.png'},
        {'id': '이탈리아', 'name': '이탈리아', 'flag': 'https://flagcdn.com/w40/it.png'},
        {'id': '스웨덴', 'name': '스웨덴', 'flag': 'https://flagcdn.com/w40/se.png'},
        {'id': '아일랜드', 'name': '아일랜드', 'flag': 'https://flagcdn.com/w40/ie.png'},
        {'id': '터키', 'name': '터키', 'flag': 'https://flagcdn.com/w40/tr.png'},
        {'id': '덴마크', 'name': '덴마크', 'flag': 'https://flagcdn.com/w40/dk.png'},
        {'id': '스위스', 'name': '스위스', 'flag': 'https://flagcdn.com/w40/ch.png'},
        {'id': '노르웨이', 'name': '노르웨이', 'flag': 'https://flagcdn.com/w40/no.png'},
#        {'id': '정보 없음', 'name': '정보 없음', 'flag': 'https://www.google.com/s2/favicons?domain=wikipedia.org&sz=128'}
    ]

    base_rec_pool = common_movies
    if not search:
        if selected_countries: base_rec_pool = base_rec_pool.filter(country_queries)
        if selected_genres: base_rec_pool = base_rec_pool.filter(genre_queries)
        if selected_otts: base_rec_pool = base_rec_pool.filter(ott_queries)

    movies = base_rec_pool
    movies_list = list(movies[:40])

    # 💡 [최종 수정] 헷갈리는 ID 대신 객체 자체를 비교하여 평점 100% 일치 보장!
    if request.user.is_authenticated:
        user_ratings = Rating.objects.filter(user=request.user, movie__in=movies_list).select_related('movie')
        rating_dict = {r.movie.id: int(r.score) for r in user_ratings if r.score}
        
        watchlists = Watchlist.objects.filter(user=request.user, movie__in=movies_list).select_related('movie')
        watchlist_set = set(w.movie.id for w in watchlists)
    else:
        rating_dict = {}
        watchlist_set = set()

    for movie in movies_list:
        movie.my_score = rating_dict.get(movie.id, 0)
        movie.is_watchlisted = movie.id in watchlist_set

    # 평점이 완벽하게 주입된 후에 정렬을 수행해야 내 평점 정렬(my_desc)이 정상 작동합니다.
    if sort == 'imdb_desc': movies_list.sort(key=lambda x: x.imdb_rating or 0, reverse=True)
    elif sort == 'imdb_asc': movies_list.sort(key=lambda x: x.imdb_rating or 0)
    elif sort == 'my_desc': movies_list.sort(key=lambda x: (x.my_score or 0, x.imdb_rating or 0), reverse=True)
    elif sort == 'my_asc': movies_list.sort(key=lambda x: (0 if (x.my_score or 0) > 0 else 1, x.my_score or 0, x.imdb_rating or 0))
    elif sort == 'votes_desc': movies_list.sort(key=lambda x: x.imdb_vote_count or 0, reverse=True)
    elif sort == 'votes_asc': movies_list.sort(key=lambda x: x.imdb_vote_count or 0)
    else: random.shuffle(movies_list)

    for movie in movies_list:
        if movie.tmdb_title and re.search(r'[가-힣]', movie.tmdb_title):
            if hasattr(movie, 'translated_title') and movie.translated_title:
                movie.translated_title = ''
                movie.save(update_fields=['translated_title'])
        movie.display_genre = get_display_genre(movie.tmdb_genre, movie.imdb_genre)
        movie.display_date = get_display_date(movie.tmdb_release_date, movie.imdb_release_date)
        movie.display_runtime = get_display_runtime(movie.tmdb_runtime, movie.imdb_runtime)
        g_val = movie.display_genre
        movie.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)
        c_val = str(movie.tmdb_production_country_kr or '')
        movie.short_country = c_val.split(',')[0].strip() + "+" if ',' in c_val else c_val

    return render(request, 'movie/rec_more_list.html', {
        'movies': movies_list, 'page_title': page_title, 'page_subtitle': page_subtitle, 'total_count': len(movies_list),
        'sort_by': sort, 'search_query': search,
        'genres_list': genres_list, 'selected_genres': selected_genres,
        'otts_list': otts_list, 'selected_otts': selected_otts,
        'countries_list': countries_list, 'selected_countries': selected_countries, 
        'selected_ratings': selected_ratings,     
        'exclude_doc': exclude_doc, 'exclude_no_rating': exclude_no_rating, 'exclude_low_votes': exclude_low_votes,
        'exclude_short': exclude_short, 'exclude_low_rating': exclude_low_rating, 'exclude_rated': exclude_rated,
        'exclude_unreleased': exclude_unreleased, 'exclude_no_imdb': exclude_no_imdb,
        'filter_submitted': 'true' if request.GET.get('filter_submitted') == 'true' else '',
    })

# 💡 [초보자 안내] 맞춤 AI TV 시리즈 추천 전체 보기 페이지
def rec_more_tv_view(request):
    user = request.user if request.user.is_authenticated else None

    # 🚀 시리즈 뷰에도 똑같이 캐시 폭파 로직 장착!
    if request.GET.get('force_refresh') == 'true' and user:
        cache.delete(f"gemini_recs_v5_{user.id}")
        cache.delete(f"gemini_fallback_v7_{user.id}")
        cache.delete(f"gemini_tv_recs_v5_{user.id}")
        cache.delete(f"gemini_tv_fallback_v7_{user.id}")
        return redirect(request.path)

    eval_count = Rating.objects.filter(user=user, tvseries__isnull=False).count() if user else 0
    is_fallback = (eval_count < 10) if user else True

    search = request.GET.get('search', '')
    sort = request.GET.get('sort', '')
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')

    # 🚀 [핵심 수정] 시리즈 화면도 처음 진입 시 exclude_rated는 꺼둠(False)!
    is_filter_action = request.GET.get('filter_submitted') == 'true'

    if not is_filter_action and not search and not sort:
        exclude_doc, exclude_no_rating, exclude_low_votes, exclude_short, exclude_low_rating, exclude_unreleased, exclude_no_imdb = True, True, True, True, True, True, True
        exclude_rated = False  # 💡 얘만 쏙 빼서 끕니다!
    else:
        exclude_doc = request.GET.get('exclude_doc') == 'on'
        exclude_no_rating = request.GET.get('exclude_no_rating') == 'on'
        exclude_low_votes = request.GET.get('exclude_low_votes') == 'on'
        exclude_short = request.GET.get('exclude_short') == 'on'
        exclude_low_rating = request.GET.get('exclude_low_rating') == 'on'
        exclude_rated = request.GET.get('exclude_rated') == 'on'
        exclude_unreleased = request.GET.get('exclude_unreleased') == 'on'
        exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on'

    base_rec_pool = TvSeries.objects.exclude(imdb_rating__lt=6.5).exclude(Q(tmdb_overview__isnull=True) | Q(tmdb_overview='') | Q(tmdb_keywords__isnull=True) | Q(tmdb_keywords='')).filter(( (Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본')) & Q(imdb_vote_count__gte=100) ) | ( (Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=2000) ) | ( ~(Q(tmdb_production_country_kr__icontains='한국') | Q(tmdb_production_country_kr__icontains='일본') | Q(tmdb_production_country_kr__icontains='인도')) & Q(imdb_vote_count__gte=500) ))

    ai_tv_qs = TvSeries.objects.none()
    if user:
        cache_key = f"gemini_tv_fallback_v7_{user.id}" if is_fallback else f"gemini_tv_recs_v5_{user.id}"
        cached_ids = cache.get(cache_key)
        
        if cached_ids: # 💡 is_fallback 여부 상관없이 10개 평가면 무조건 폭파
            rated_ids = set(Rating.objects.filter(user=user).values_list('tvseries__id', flat=True))
            if sum(1 for mid in cached_ids if mid in rated_ids) >= 10:
                cache.delete(cache_key)
                cache.delete(f"gemini_recs_v5_{user.id}")
                cache.delete(f"gemini_fallback_v7_{user.id}")
                cached_ids = None

        if not cached_ids:
            if not is_fallback:
                get_gemini_tv_recommendations(user, base_rec_pool)
                cached_ids = cache.get(cache_key, [])
                
            if not cached_ids or is_fallback:
                is_fallback = True
                cache_key = f"gemini_tv_fallback_v7_{user.id}"
                rated_ids = set(Rating.objects.filter(user=user).values_list('tvseries__id', flat=True))
                watchlisted_ids = set(Watchlist.objects.filter(user=user).values_list('tvseries__id', flat=True))
                seen_ids = rated_ids | watchlisted_ids
                
                pool_unseen = base_rec_pool.exclude(id__in=seen_ids)
                kr_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
                jp_candidates = list(pool_unseen.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
                others_candidates = list(pool_unseen.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
                
                fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
                cached_ids = [m.id for m in fallback_40]
                cache.set(cache_key, cached_ids, timeout=86400)

        ai_tv_qs = TvSeries.objects.filter(id__in=cached_ids)
        page_title = '📺 기본 추천 시리즈 40편' if is_fallback else '✨ 맞춤형 AI 추천 [시리즈]'
        page_subtitle = '(10건 이상 평가하고 맞춤 AI 추천 받기)' if is_fallback else ''
    else:
        cache_key_anon = "gemini_tv_rec_master_pool_anon_v7"
        cached_anon_ids = cache.get(cache_key_anon)
        if not cached_anon_ids:
            kr_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='한국').order_by('-imdb_vote_count')[:10])
            jp_candidates = list(base_rec_pool.filter(tmdb_production_country_kr__icontains='일본').exclude(tmdb_genre__icontains='애니메이션').order_by('-imdb_vote_count')[:10])
            others_candidates = list(base_rec_pool.exclude(id__in=[m.id for m in kr_candidates + jp_candidates]).order_by('-imdb_vote_count')[:50])
            fallback_40 = kr_candidates[:3] + jp_candidates[:2] + others_candidates[:35]
            cached_anon_ids = [m.id for m in fallback_40]
            cache.set(cache_key_anon, cached_anon_ids, timeout=86400)
            
        ai_tv_qs = TvSeries.objects.filter(id__in=cached_anon_ids)
        page_title = '📺 오늘의 강력 추천 시리즈'
        page_subtitle = '(로그인하고 맞춤 AI 추천받기)'

    common_series = ai_tv_qs

    # 💡 [핵심] TV 시리즈 더보기 화면에서도 검색어가 존재할 경우, 모든 필터를 무시하고 스캔!
    if search:
        q_cond = Q(tmdb_title__icontains=search)
        if hasattr(common_series.model, 'tmdb_original_title'): q_cond |= Q(tmdb_original_title__icontains=search)
        if hasattr(common_series.model, 'translated_title'): q_cond |= Q(translated_title__icontains=search)
        if hasattr(common_series.model, 'tmdb_actors'): q_cond |= Q(tmdb_actors__icontains=search)
        common_series = common_series.filter(q_cond)

    if not search:
        if exclude_no_imdb: common_series = common_series.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))
        if exclude_doc: common_series = common_series.exclude(Q(tmdb_genre__icontains='다큐') | Q(Q(tmdb_genre='') | Q(tmdb_genre__isnull=True) | Q(tmdb_genre='None'), imdb_genre__icontains='Documentary'))
        if exclude_no_rating: common_series = common_series.exclude(imdb_rating=0.0)
        if exclude_low_votes: common_series = common_series.filter(imdb_vote_count__gte=10)
        if exclude_short: common_series = common_series.exclude(Q(tmdb_runtime__gt=0, tmdb_runtime__lte=20) | Q(Q(tmdb_runtime=0) | Q(tmdb_runtime__isnull=True), imdb_runtime__gt=0, imdb_runtime__lte=20))
        if exclude_low_rating: common_series = common_series.exclude(imdb_rating__lt=5.0)
        if exclude_rated and user: common_series = common_series.exclude(id__in=Rating.objects.filter(user=user, tvseries__isnull=False).values('tvseries__id'))
        if exclude_unreleased:
            today_date = str(timezone.now().date())[:4]
            common_series = common_series.exclude(imdb_release_date__gt=today_date)

        if selected_ratings:
            rating_q = Q()
            for r_val in selected_ratings:
                if r_val == 'ALL': rating_q |= (Q(tmdb_certification_kr__in=['ALL', 'All', '전체', 'G']) | Q(tmdb_certification_kr__icontains='전체') | Q(tmdb_certification_us__in=['G', 'TV-G', 'TV-Y', 'TV-Y7']))
                elif r_val == '12': rating_q |= (Q(tmdb_certification_kr__icontains='12') | Q(tmdb_certification_us__in=['PG', 'TV-PG']))
                elif r_val == '15': rating_q |= (Q(tmdb_certification_kr__icontains='15') | Q(tmdb_certification_us__in=['PG-13', 'TV-14']))
                elif r_val == '19': rating_q |= (Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | Q(tmdb_certification_kr__icontains='청불') | Q(tmdb_certification_us__in=['R', 'NC-17', 'TV-MA']))
                elif r_val == '정보 없음': rating_q |= (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급', 'None']) | Q(tmdb_certification_kr__isnull=True))
            common_series = common_series.filter(rating_q)

    country_queries = Q()
    if selected_countries:
        for c in selected_countries:
            if c == '정보 없음': country_queries |= (Q(tmdb_production_country_kr__isnull=True) | Q(tmdb_production_country_kr='') | Q(tmdb_production_country_kr='None'))
            else: country_queries |= Q(tmdb_production_country_kr=c)

    genre_queries = Q()
    if selected_genres:
        for genre in selected_genres:
            if genre == '정보 없음': genre_queries |= (Q(tmdb_genre__isnull=True) | Q(tmdb_genre='') | Q(tmdb_genre='None')) & (Q(imdb_genre__isnull=True) | Q(imdb_genre='') | Q(imdb_genre='None'))
            else:
                q = Q(tmdb_genre__icontains=genre)
                for en_g, kr_g in IMDB_GENRE_MAP.items():
                    if kr_g == genre: q |= Q(imdb_genre__icontains=en_g)
                genre_queries |= q

    ott_queries = Q()
    if selected_otts:
        for ott in selected_otts: ott_queries |= Q(tmdb_streaming_providers__icontains=ott)

    genre_base = common_series
    if not search:
        if selected_countries: genre_base = genre_base.filter(country_queries)
        if selected_otts: genre_base = genre_base.filter(ott_queries)
    genres_list = get_all_genres(genre_base)

    ott_base = common_series
    if not search:
        if selected_countries: ott_base = ott_base.filter(country_queries)
        if selected_genres: ott_base = ott_base.filter(genre_queries)
    otts_list = get_ott_list_with_logos(ott_base)

    country_base = common_series
    if not search:
        if selected_genres: country_base = country_base.filter(genre_queries)
        if selected_otts: country_base = country_base.filter(ott_queries)
    # 💡 국기 이모지가 포함된 국가 리스트 (id: DB조회용, name: 화면표시용)
    # 💡 윈도우에서도 절대 안 깨지는 고화질 국기 이미지 적용 
    countries_list = [
        {'id': '한국', 'name': '한국', 'flag': 'https://flagcdn.com/w40/kr.png'},
        {'id': '미국', 'name': '미국', 'flag': 'https://flagcdn.com/w40/us.png'},
        {'id': '영국', 'name': '영국', 'flag': 'https://flagcdn.com/w40/gb.png'},
        {'id': '일본', 'name': '일본', 'flag': 'https://flagcdn.com/w40/jp.png'},
        {'id': '중국', 'name': '중국', 'flag': 'https://flagcdn.com/w40/cn.png'},
        {'id': '홍콩', 'name': '홍콩', 'flag': 'https://flagcdn.com/w40/hk.png'},
        {'id': '인도', 'name': '인도', 'flag': 'https://flagcdn.com/w40/in.png'},
        {'id': '프랑스', 'name': '프랑스', 'flag': 'https://flagcdn.com/w40/fr.png'},
        {'id': '캐나다', 'name': '캐나다', 'flag': 'https://flagcdn.com/w40/ca.png'},
        {'id': '독일', 'name': '독일', 'flag': 'https://flagcdn.com/w40/de.png'},
        {'id': '스페인', 'name': '스페인', 'flag': 'https://flagcdn.com/w40/es.png'},
        {'id': '벨기에', 'name': '벨기에', 'flag': 'https://flagcdn.com/w40/be.png'},
        {'id': '호주', 'name': '호주', 'flag': 'https://flagcdn.com/w40/au.png'},
        {'id': '이탈리아', 'name': '이탈리아', 'flag': 'https://flagcdn.com/w40/it.png'},
        {'id': '스웨덴', 'name': '스웨덴', 'flag': 'https://flagcdn.com/w40/se.png'},
        {'id': '아일랜드', 'name': '아일랜드', 'flag': 'https://flagcdn.com/w40/ie.png'},
        {'id': '터키', 'name': '터키', 'flag': 'https://flagcdn.com/w40/tr.png'},
        {'id': '덴마크', 'name': '덴마크', 'flag': 'https://flagcdn.com/w40/dk.png'},
        {'id': '스위스', 'name': '스위스', 'flag': 'https://flagcdn.com/w40/ch.png'},
        {'id': '노르웨이', 'name': '노르웨이', 'flag': 'https://flagcdn.com/w40/no.png'},
#        {'id': '정보 없음', 'name': '정보 없음', 'flag': 'https://www.google.com/s2/favicons?domain=wikipedia.org&sz=128'}
    ]

    base_rec_pool = common_series
    if not search:
        if selected_countries: base_rec_pool = base_rec_pool.filter(country_queries)
        if selected_genres: base_rec_pool = base_rec_pool.filter(genre_queries)
        if selected_otts: base_rec_pool = base_rec_pool.filter(ott_queries)

    series_qs = base_rec_pool
    series_list = list(series_qs[:40])

    # 💡 [최종 수정] 헷갈리는 ID 대신 객체 자체를 비교하여 평점 100% 일치 보장!
    if request.user.is_authenticated:
        user_ratings = Rating.objects.filter(user=request.user, tvseries__in=series_list).select_related('tvseries')
        rating_dict = {r.tvseries.id: int(r.score) for r in user_ratings if r.score}
        
        watchlists = Watchlist.objects.filter(user=request.user, tvseries__in=series_list).select_related('tvseries')
        watchlist_set = set(w.tvseries.id for w in watchlists)
    else:
        rating_dict = {}
        watchlist_set = set()

    for m in series_list:
        m.my_score = rating_dict.get(m.id, 0)
        m.is_watchlisted = m.id in watchlist_set

    # 평점이 완벽하게 주입된 후에 정렬을 수행합니다.
    if sort == 'imdb_desc': series_list.sort(key=lambda x: x.imdb_rating or 0, reverse=True)
    elif sort == 'imdb_asc': series_list.sort(key=lambda x: x.imdb_rating or 0)
    elif sort == 'my_desc': series_list.sort(key=lambda x: (x.my_score or 0, x.imdb_rating or 0), reverse=True)
    elif sort == 'my_asc': series_list.sort(key=lambda x: (0 if (x.my_score or 0) > 0 else 1, x.my_score or 0, x.imdb_rating or 0))
    elif sort == 'votes_desc': series_list.sort(key=lambda x: x.imdb_vote_count or 0, reverse=True)
    elif sort == 'votes_asc': series_list.sort(key=lambda x: x.imdb_vote_count or 0)
    else: random.shuffle(series_list)

    for m in series_list:
        if m.tmdb_title and re.search(r'[가-힣]', m.tmdb_title):
            if hasattr(m, 'translated_title') and m.translated_title:
                m.translated_title = ''
                m.save(update_fields=['translated_title'])
        m.display_genre = get_display_genre(m.tmdb_genre, m.imdb_genre)
        m.display_date = get_display_date(m.tmdb_release_date, m.imdb_release_date)
        m.display_runtime = get_display_runtime(m.tmdb_runtime, m.imdb_runtime)
        g_val = m.display_genre
        m.short_genre = g_val.split(',')[0].strip() + "+" if ',' in g_val else (g_val.split('/')[0].strip() + "+" if '/' in g_val else g_val)
        c_val = str(m.tmdb_production_country_kr or '')
        m.short_country = c_val.split(',')[0].strip() + "+" if ',' in c_val else c_val

    return render(request, 'movie/rec_more_list.html', {
        'movies': series_list, 'page_title': page_title, 'page_subtitle': page_subtitle, 'total_count': len(series_list),
        'sort_by': sort, 'search_query': search,
        'genres_list': genres_list, 'selected_genres': selected_genres,
        'otts_list': otts_list, 'selected_otts': selected_otts,
        'countries_list': countries_list, 'selected_countries': selected_countries, 
        'selected_ratings': selected_ratings,     
        'exclude_doc': exclude_doc, 'exclude_no_rating': exclude_no_rating, 'exclude_low_votes': exclude_low_votes,
        'exclude_short': exclude_short, 'exclude_low_rating': exclude_low_rating,
        'exclude_unreleased': exclude_unreleased, 'exclude_no_imdb': exclude_no_imdb,
        'filter_submitted': 'true' if request.GET.get('filter_submitted') == 'true' else '',
        'is_tv': True, 
    })

# ==============================================================================
# [SECTION 5] 전체 목록 뷰 (All List)
# ==============================================================================
# 💡 [초보자 안내] 전체 콘텐츠 목록(영화, TV 통합) 무한 스크롤 뷰입니다.
def all_list(request):
    search_query = request.GET.get('search', '').strip()
    req_type = request.GET.get('type', '').lower()

    # =========================================================
    # 🚀 [검색 엔진 전처리] 동의어 변환 및 키워드/정규식 생성
    # =========================================================
    regex_str = ""
    search_keywords = [] # 💡 파이썬 JSON 스캔 시 사용할 키워드 묶음
    live_search_terms = [] # 💡 실시간 팝업용 가벼운 키워드 묶음

    if search_query:
        # 1. 원본 검색어 보존 (띄어쓰기 무시용)
        q_clean_orig = search_query.replace(' ', '').lower()
        regex_orig = r'\s*'.join(re.escape(char) for char in q_clean_orig)

        # 2. 미니 동의어 사전 (오타 및 외래어 표기법 교정)
        synonyms = {
            # 🦸‍♂️ 프랜차이즈 / 영화 제목 오타 방어
            '어벤져스': '어벤저스',
            '베트맨': '배트맨',
            '수퍼맨': '슈퍼맨',
            '에일리언': '에이리언',
            '주라기': '쥬라기',
            '케리비안': '캐리비안',
            '인디애나': '인디아나',
            '메트릭스': '매트릭스',
            '터미네타': '터미네이터',
            '스타트랙': '스타트렉',

            # 👤 해외 배우/감독 이름 방어 (띄어쓰기, 붙여쓰기 모두 대비)
            '탐 크루즈': '톰 크루즈', '탐크루즈': '톰크루즈',
            '탐 하디': '톰 하디', '탐하디': '톰하디',
            '탐 홀랜드': '톰 홀랜드', '탐홀랜드': '톰홀랜드',
            '탐 행크스': '톰 행크스', '탐행크스': '톰행크스',
            '브레드 피트': '브래드 피트', '브레드피트': '브래드피트',
            '죠니 뎁': '조니 뎁', '죠니뎁': '조니뎁',
            '엔젤리나 졸리': '안젤리나 졸리', '엔젤리나졸리': '안젤리나졸리',
            
            # (이름의 일부만 쓰여도 안전한 고유명사들)
            '레오날도': '레오나르도',  # 레오날도 디카프리오
            '조한슨': '요한슨',      # 스칼렛 조한슨 -> 스칼렛 요한슨
            '슈왈츠제네거': '슈워제네거', '슈왈제네거': '슈워제네거',
            '카메룬': '카메론',      # 제임스 카메룬 -> 카메론 (아바타 감독)
            '놀런': '놀란',        # 크리스토퍼 놀런 -> 크리스토퍼 놀란
            '질렌홀': '질렌할',      # 제이크 질렌홀 -> 질렌할
            '펠트로': '팰트로',      # 기네스 펠트로 -> 팰트로

            # 🎬 장르 및 영화 용어 오타 방어
            '코메디': '코미디',
            '미스테리': '미스터리',
            '환타지': '판타지',
            '느와르': '누아르',
            '에니메이션': '애니메이션',
            '에니': '애니',

            # 🚀 [핵심 추가] 영어 검색어 -> 한글 치환 (외국 배우/시리즈 대응)
            'cruise': '크루즈', 'tom': '톰', 'brad': '브래드', 'pitt': '피트', 
            'spider': '스파이더', 'man': '맨', 'batman': '배트맨', 'superman': '슈퍼맨',
            'iron': '아이언'
        }
        processed_query = search_query.lower()
        for key, val in synonyms.items():
            processed_query = processed_query.replace(key, val)
        
        q_clean_syn = processed_query.replace(' ', '')
        regex_syn = r'\s*'.join(re.escape(char) for char in q_clean_syn)

        # 3. [결과창용 무적 정규식] 원본과 다르면 OR(|)로 합치기
        if regex_orig != regex_syn:
            regex_str = f"({regex_orig}|{regex_syn})"
            search_keywords = [q_clean_orig, q_clean_syn]
        else:
            regex_str = regex_orig
            search_keywords = [q_clean_orig]

        # 4. [팝업용 초고속 키워드] 띄어쓰기 유무를 조합한 순수 문자열 (DB 부하 최소화)
        live_search_terms = list(set([
            search_query.lower(),
            processed_query,
            q_clean_orig,
            q_clean_syn
        ]))

    # 브라우저가 '실시간 검색'을 요청하면 HTML 페이지 대신 순수 데이터만 즉시 반환합니다.
    # =========================================================
    # 🚀 [초고속 모드] 실시간 검색창 팝업 로직 (구시간 탈출!)
    # =========================================================
    if request.GET.get('live_search') == 'true':
        if not search_query:
            return JsonResponse({'results': [], 'movie_count': 0, 'tv_count': 0, 'people_count': 0})
        
        # 💡 [캐싱] 로직이 바뀌었으니 캐시를 v5로 격상시킵니다!
        cache_key = f"live_search_v5_{search_query}"
        cached_response = cache.get(cache_key)
        if cached_response:
            return JsonResponse(cached_response)
        
        # 🚀 [핵심 최적화] 무거운 iregex 대신 엄청나게 가벼운 icontains 사용!
        m_cond_live = Q()
        t_cond_live = Q()
        
        for term in live_search_terms:
            if not term: continue
            
            # 영화 스캔
            m_cond_live |= Q(tmdb_title__icontains=term) | Q(tmdb_original_title__icontains=term) | Q(tmdb_actors__icontains=term) | Q(tmdb_director__icontains=term)
            if hasattr(Movie, 'translated_title'): m_cond_live |= Q(translated_title__icontains=term)
            if hasattr(Movie, 'tmdb_actor_details'): m_cond_live |= Q(tmdb_actor_details__icontains=term)
            
            # 시리즈 스캔
            t_cond_live |= Q(tmdb_title__icontains=term) | Q(tmdb_original_title__icontains=term) | Q(tmdb_actors__icontains=term) | Q(tmdb_director__icontains=term)
            if hasattr(TvSeries, 'translated_title'): t_cond_live |= Q(translated_title__icontains=term)
            if hasattr(TvSeries, 'tmdb_actor_details'): t_cond_live |= Q(tmdb_actor_details__icontains=term)
        
        m_qs = Movie.objects.filter(m_cond_live).order_by('-imdb_vote_count', '-id')
        m_count = m_qs.count()
        top_movies = list(m_qs[:5])

        t_qs = TvSeries.objects.filter(t_cond_live).order_by('-imdb_vote_count', '-id')
        t_count = t_qs.count()
        top_series = list(t_qs[:5])

        # 3. 인물(배우/감독/각본가) 검색 로직
        matched_people = {}
        def extract_people(queryset):
            # 🚀 [핵심] 상위 대작 50개만 스캔하여 속도 쾌속 + 인지도순 탐색
            for item in queryset[:50]: 
                item_votes = getattr(item, 'imdb_vote_count', 0) or 0
                
                # 🎭 [배우 찾기]
                actors = getattr(item, 'tmdb_actor_details', [])
                if isinstance(actors, str):
                    try: actors = json.loads(actors)
                    except Exception: actors = []
                if isinstance(actors, list):
                    for actor in actors:
                        actor_name = str(actor.get('name', '')).replace(' ', '').lower()
                        actor_original = str(actor.get('original_name', '')).replace(' ', '').lower()
                        
                        # 🚀 [핵심] 원본어(cruise)와 치환어(크루즈) 중 하나라도 걸리면 무조건 캐치!
                        if any(kw in actor_name or (kw and kw in actor_original) for kw in search_keywords):
                            pid = actor.get('id')
                            if pid:
                                if pid not in matched_people:
                                    matched_people[pid] = {'id': pid, 'name': actor.get('name'), 'profile_url': actor.get('profile_url', ''), 'type': '배우', 'score': 0}
                                matched_people[pid]['score'] += item_votes
                
                # 🎬 [감독 찾기]
                director = str(getattr(item, 'tmdb_director', '') or '')
                dir_clean = director.replace(' ', '').lower()
                if any(kw in dir_clean for kw in search_keywords):
                    did = getattr(item, 'tmdb_director_id', None)
                    if did:
                        if did not in matched_people:
                            matched_people[did] = {'id': did, 'name': director, 'profile_url': getattr(item, 'tmdb_director_image_url', ''), 'type': '감독', 'score': 0}
                        matched_people[did]['score'] += item_votes
                
                # ✍️ [각본가 찾기]
                writer = str(getattr(item, 'tmdb_screenwriter', '') or '')
                wrt_clean = writer.replace(' ', '').lower()
                if any(kw in wrt_clean for kw in search_keywords):
                    wid = getattr(item, 'tmdb_screenwriter_id', None)
                    if wid:
                        if wid not in matched_people:
                            matched_people[wid] = {'id': wid, 'name': writer, 'profile_url': '', 'type': '각본가', 'score': 0}
                        matched_people[wid]['score'] += item_votes

        extract_people(m_qs)
        extract_people(t_qs)
        
        # 🚀 [업그레이드] 투표수 합산 점수(score) 기준으로 내림차순 정렬 후 컷!
        sorted_people = sorted(matched_people.values(), key=lambda x: x['score'], reverse=True)
        max_people = 3 if len(search_query) == 1 else 5
        people_list = sorted_people[:max_people]

        # 4. 결과 통합 (인물은 상단 배치)
        combined = []
        for p in people_list:
            combined.append({
                'id': p['id'], 'type': 'person', 'type_label': p['type'], 'color': '#ec4899', 
                'title': p['name'], 'year': '', 'votes': 9999999, 
                'img': p['profile_url']
            })
        for m in top_movies:
            combined.append({
                'id': m.id, 'type': 'movie', 'type_label': '영화', 'color': '#0d6efd',
                'title': getattr(m, 'tmdb_title', ''),
                'year': str(getattr(m, 'tmdb_release_date', ''))[:4] if getattr(m, 'tmdb_release_date', None) else '연도미상',
                'votes': getattr(m, 'imdb_vote_count', 0) or 0,
                'img': getattr(m, 'tmdb_poster_url', '') or ''
            })
        for s in top_series:
            release_val = getattr(s, 'tmdb_release_date', getattr(s, 'first_air_date', None))
            combined.append({
                'id': s.id, 'type': 'tv', 'type_label': '시리즈', 'color': '#10b981',
                'title': getattr(s, 'tmdb_title', ''),
                'year': str(release_val)[:4] if release_val else '연도미상',
                'votes': getattr(s, 'imdb_vote_count', 0) or 0,
                'img': getattr(s, 'tmdb_poster_url', getattr(s, 'poster_url', '')) or ''
            })
        
        combined.sort(key=lambda x: x['votes'], reverse=True)

        # 🚀 [핵심 2] 허용된 인물 수(3 or 5) + 고정 작품 수(5) = 총 8개 또는 10개만 리턴!
        max_results = max_people + 5

        final_response_data = {
            'results': combined[:max_results],
            'movie_count': m_count,
            'tv_count': t_count,
            'people_count': len(matched_people)
        }

        # 💡 [캐시 저장] 찾은 결과를 메모리에 1시간 보관
        cache.set(cache_key, final_response_data, timeout=3600)

        return JsonResponse(final_response_data)


    # 🚀 [핵심 1] 스마트 자동 탭 전환 로직 (엔터 치고 전체 결과로 넘어갔을 때)
    content_type = req_type
    if search_query and not req_type:
        # icontains 대신 iregex 적용
        m_cond = Q(tmdb_title__iregex=regex_str)
        if hasattr(Movie, 'translated_title'): m_cond |= Q(translated_title__iregex=regex_str)
        if len(search_query) > 1:
            if hasattr(Movie, 'tmdb_original_title'): m_cond |= Q(tmdb_original_title__iregex=regex_str)
            if hasattr(Movie, 'tmdb_actors'): m_cond |= Q(tmdb_actors__iregex=regex_str)
            if hasattr(Movie, 'tmdb_actor_details'): m_cond |= Q(tmdb_actor_details__iregex=regex_str)
        
        m_count = Movie.objects.filter(m_cond).count()
        
        if m_count == 0:
            t_cond = Q(tmdb_title__iregex=regex_str)
            if hasattr(TvSeries, 'translated_title'): t_cond |= Q(translated_title__iregex=regex_str)
            if len(search_query) > 1:
                if hasattr(TvSeries, 'tmdb_original_title'): t_cond |= Q(tmdb_original_title__iregex=regex_str)
                if hasattr(TvSeries, 'tmdb_actors'): t_cond |= Q(tmdb_actors__iregex=regex_str)
                if hasattr(TvSeries, 'tmdb_actor_details'): t_cond |= Q(tmdb_actor_details__iregex=regex_str)
            
            t_count = TvSeries.objects.filter(t_cond).count()
            if t_count > 0:
                content_type = 'tv'
    
    if not content_type:
        content_type = 'movie'

    # 💡 [절대 방어] 영화든 TV 시리즈든 무조건 IMDb ID가 있는 것만 가져옵니다!
    if content_type == 'tv':
        base_queryset = TvSeries.objects.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))
    else:
        base_queryset = Movie.objects.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id=''))

    # (이 사이에 있는 COUNTRY_KR_MAP 등 1. 💡 스마트 국가/장르 매핑 사전 준비 코드는 그대로 둡니다.)

    # 1. 💡 스마트 국가/장르 매핑 사전 준비
    COUNTRY_KR_MAP = {
        'KR': '한국', 'US': '미국', 'JP': '일본', 'GB': '영국', 'UK': '영국', 'CN': '중국', 'FR': '프랑스', 'DE': '독일', 'CA': '캐나다',
        'ES': '스페인', 'IT': '이탈리아', 'TW': '대만', 'HK': '홍콩', 'South Korea': '한국', 'United States of America': '미국',
        'United States': '미국', 'Japan': '일본', 'United Kingdom': '영국', 'China': '중국', 'France': '프랑스', 'Germany': '독일',
        'Canada': '캐나다', 'Spain': '스페인', 'Italy': '이탈리아', 'Taiwan': '대만', 'Hong Kong': '홍콩',
    }
    GENRE_SYNONYMS = {
        'SF': ['SF', 'Sci-Fi', 'Science Fiction', 'Sci-Fi & Fantasy', '공상과학'], '판타지': ['판타지', 'Fantasy', 'Sci-Fi & Fantasy'],
        '액션': ['액션', 'Action', 'Action & Adventure'], '모험': ['모험', 'Adventure', 'Action & Adventure', '어드벤처'],
        '전쟁': ['전쟁', 'War', 'War & Politics', '밀리터리'], '역사': ['역사', 'History', 'War & Politics', '사극', '시대극'],
        '가족': ['가족', 'Family', 'Kids', '어린이'], '어린이': ['가족', 'Kids', '어린이', 'Family'],
        '드라마': ['드라마', 'Drama', 'Soap', '소프'], '리얼리티': ['리얼리티', 'Reality', 'Reality-TV'], '토크쇼': ['토크쇼', 'Talk', 'Talk-Show'],
        '뉴스': ['뉴스', 'News'], 'TV 영화': ['TV 영화', 'TV Movie', '단편'], '코미디': ['코미디', 'Comedy', '개그', '유머'],
        '범죄': ['범죄', 'Crime', '느와르'], '공포': ['공포', 'Horror', '호러', '스릴', '무서운'], '로맨스': ['로맨스', 'Romance', '멜로', '로맨틱', '사랑'],
        '스릴러': ['스릴러', 'Thriller', '서스펜스'], '미스터리': ['미스터리', 'Mystery', '추리'], '음악': ['음악', 'Music', '뮤지컬', 'Musical'],
        '서부': ['서부', 'Western', '웨스턴'], '다큐멘터리': ['다큐멘터리', 'Documentary', '다큐'], '애니메이션': ['애니메이션', 'Animation', '애니', '만화'],
    }

    # 🚀 [핵심 2] 실제 데이터베이스 필터링 부분 (정규식 검색 최적화)
    if search_query:
        q_cond = Q(tmdb_title__iregex=regex_str)
        if hasattr(base_queryset.model, 'translated_title'): 
            q_cond |= Q(translated_title__iregex=regex_str)
        
        # 💡 한 글자 검색 시에는 배우나 원제까지 스캔하지 않도록 방어!
        if len(search_query) > 1:
            if hasattr(base_queryset.model, 'tmdb_original_title'): 
                q_cond |= Q(tmdb_original_title__iregex=regex_str)
            if hasattr(base_queryset.model, 'tmdb_actors'): 
                q_cond |= Q(tmdb_actors__iregex=regex_str)
            if hasattr(base_queryset.model, 'tmdb_actor_details'): 
                q_cond |= Q(tmdb_actor_details__iregex=regex_str)
                
        base_queryset = base_queryset.filter(q_cond)

    # 3. 💡 드롭다운 필터 재료 생성 (제외 필터 적용 전 순수 마스터셋)
    master_qs = TvSeries.objects.all() if content_type == 'tv' else Movie.objects.all()
    try:
        genres_list = get_all_genres(master_qs)
        otts_list = get_ott_list_with_logos(master_qs)
    except NameError:
        genres_list = ['SF', '액션', '코미디', '드라마', '로맨스', '스릴러', '공포', '애니메이션', '판타지', '범죄', '모험', '미스터리', '전쟁', '가족', '음악', '역사', '서부', '다큐멘터리']
        otts_list = [
            {'id': 'Netflix', 'name': '넷플릭스', 'logo': ''}, {'id': 'TVING', 'name': '티빙', 'logo': ''},
            {'id': 'Wavve', 'name': '웨이브', 'logo': ''}, {'id': 'Disney Plus', 'name': '디즈니+', 'logo': ''},
            {'id': 'Coupang Play', 'name': '쿠팡플레이', 'logo': ''}, {'id': 'Watcha', 'name': '왓챠', 'logo': ''},
            {'id': 'Apple TV Plus', 'name': '애플 TV+', 'logo': ''},
        ]

    # 💡 국기 이모지가 포함된 국가 리스트 (id: DB조회용, name: 화면표시용)
    # 💡 윈도우에서도 절대 안 깨지는 고화질 국기 이미지 적용 
    countries_list = [
        {'id': '한국', 'name': '한국', 'flag': 'https://flagcdn.com/w40/kr.png'},
        {'id': '미국', 'name': '미국', 'flag': 'https://flagcdn.com/w40/us.png'},
        {'id': '영국', 'name': '영국', 'flag': 'https://flagcdn.com/w40/gb.png'},
        {'id': '일본', 'name': '일본', 'flag': 'https://flagcdn.com/w40/jp.png'},
        {'id': '중국', 'name': '중국', 'flag': 'https://flagcdn.com/w40/cn.png'},
        {'id': '홍콩', 'name': '홍콩', 'flag': 'https://flagcdn.com/w40/hk.png'},
        {'id': '인도', 'name': '인도', 'flag': 'https://flagcdn.com/w40/in.png'},
        {'id': '프랑스', 'name': '프랑스', 'flag': 'https://flagcdn.com/w40/fr.png'},
        {'id': '캐나다', 'name': '캐나다', 'flag': 'https://flagcdn.com/w40/ca.png'},
        {'id': '독일', 'name': '독일', 'flag': 'https://flagcdn.com/w40/de.png'},
        {'id': '스페인', 'name': '스페인', 'flag': 'https://flagcdn.com/w40/es.png'},
        {'id': '벨기에', 'name': '벨기에', 'flag': 'https://flagcdn.com/w40/be.png'},
        {'id': '호주', 'name': '호주', 'flag': 'https://flagcdn.com/w40/au.png'},
        {'id': '이탈리아', 'name': '이탈리아', 'flag': 'https://flagcdn.com/w40/it.png'},
        {'id': '스웨덴', 'name': '스웨덴', 'flag': 'https://flagcdn.com/w40/se.png'},
        {'id': '아일랜드', 'name': '아일랜드', 'flag': 'https://flagcdn.com/w40/ie.png'},
        {'id': '터키', 'name': '터키', 'flag': 'https://flagcdn.com/w40/tr.png'},
        {'id': '덴마크', 'name': '덴마크', 'flag': 'https://flagcdn.com/w40/dk.png'},
        {'id': '스위스', 'name': '스위스', 'flag': 'https://flagcdn.com/w40/ch.png'},
        {'id': '노르웨이', 'name': '노르웨이', 'flag': 'https://flagcdn.com/w40/no.png'},
#        {'id': '정보 없음', 'name': '정보 없음', 'flag': 'https://www.google.com/s2/favicons?domain=wikipedia.org&sz=128'}
    ]

    # 4. 💡 8대 필터 파라미터 수신 (이 주석 아래부터 덮어쓰기!)
    selected_genres = request.GET.getlist('genres')
    selected_otts = request.GET.getlist('otts')
    selected_ratings = request.GET.getlist('ratings')
    selected_countries = request.GET.getlist('countries')
    filter_submitted = request.GET.get('filter_submitted', '')

    exclude_rated = request.GET.get('exclude_rated') == 'on'
    exclude_no_imdb = request.GET.get('exclude_no_imdb') == 'on' or (filter_submitted != 'true')
    
    # =====================================================================
    # 💡 [수정] 무평점, 5점 미만 제외는 슬라이더가 대신하므로 무조건 False 처리!
    # =====================================================================
    exclude_no_rating = False
    exclude_low_rating = False
    
    exclude_low_votes = request.GET.get('exclude_low_votes') == 'on' or (filter_submitted != 'true')
    exclude_doc = request.GET.get('exclude_doc') == 'on' or (filter_submitted != 'true')
    exclude_short = request.GET.get('exclude_short') == 'on' or (filter_submitted != 'true')
    exclude_unreleased = request.GET.get('exclude_unreleased') == 'on' or (filter_submitted != 'true')

    # =====================================================================
    # 💡 [추가] 다큐멘터리 장르 선택 시, 다큐 제외 옵션을 강제로 꺼줍니다!
    # =====================================================================
    if '다큐멘터리' in selected_genres:
        exclude_doc = False

    # 💡 [핵심] 검색어가 없을 때만 제외 필터 및 선택 필터를 가동 (검색 시 풀이 잘려나가는 것 완벽 방지!)
    if not search_query:
        if exclude_doc and hasattr(base_queryset.model, 'tmdb_genre'):
            base_queryset = base_queryset.exclude(Q(tmdb_genre__icontains='다큐') | Q(tmdb_genre__icontains='Documentary'))

    # =====================================================
    # 💡 [추가] 통합 필터 슬라이더 파라미터 수신
    # =====================================================
    rating_min = request.GET.get('rating_min', '1')
    rating_max = request.GET.get('rating_max', '10')
    period_min_idx = int(request.GET.get('period_min_idx', '0'))
    period_max_idx = int(request.GET.get('period_max_idx', '8'))
    age_min_idx = int(request.GET.get('age_min_idx', '0'))
    age_max_idx = int(request.GET.get('age_max_idx', '3'))

    # 💡 [핵심] 검색어가 없을 때만 제외 필터 및 선택 필터를 가동 (검색 시 풀이 잘려나가는 것 완벽 방지!)
    if not search_query:
        if exclude_doc and hasattr(base_queryset.model, 'tmdb_genre'):
            base_queryset = base_queryset.exclude(Q(tmdb_genre__icontains='다큐') | Q(tmdb_genre__icontains='Documentary'))
        if exclude_no_imdb and hasattr(base_queryset.model, 'imdb_rating'):
            base_queryset = base_queryset.exclude(Q(imdb_rating__isnull=True) | Q(imdb_rating=0))
        if exclude_no_rating and hasattr(base_queryset.model, 'imdb_vote_count'):
            base_queryset = base_queryset.exclude(Q(imdb_vote_count__isnull=True) | Q(imdb_vote_count=0))
        if exclude_low_rating and hasattr(base_queryset.model, 'imdb_rating'):
            base_queryset = base_queryset.filter(imdb_rating__gte=5.0)
        if exclude_low_votes and hasattr(base_queryset.model, 'imdb_vote_count'):
            min_votes = 30 if content_type == 'tv' else 100
            base_queryset = base_queryset.filter(imdb_vote_count__gte=min_votes)
        if exclude_unreleased:
            today_year = str(timezone.now().date())[:4]
            if content_type == 'tv':
                if hasattr(base_queryset.model, 'first_air_date'): base_queryset = base_queryset.exclude(Q(first_air_date__isnull=True) | Q(first_air_date__gt=timezone.now().date()))
                elif hasattr(base_queryset.model, 'imdb_release_date'): base_queryset = base_queryset.exclude(imdb_release_date__gt=today_year)
            else:
                if hasattr(base_queryset.model, 'tmdb_release_date'): base_queryset = base_queryset.exclude(Q(tmdb_release_date__isnull=True) | Q(tmdb_release_date__gt=timezone.now().date()))
        if exclude_short:
            min_runtime = 15 if content_type == 'tv' else 60
            if hasattr(base_queryset.model, 'tmdb_runtime'): base_queryset = base_queryset.exclude(Q(tmdb_runtime__gt=0, tmdb_runtime__lte=min_runtime))
            elif hasattr(base_queryset.model, 'runtime'): base_queryset = base_queryset.exclude(Q(runtime__gt=0, runtime__lte=min_runtime))
        if exclude_rated and request.user.is_authenticated:
            if content_type == 'tv' and hasattr(Rating, 'tvseries'): rated_ids = Rating.objects.filter(user=request.user, score__gt=0, tvseries__isnull=False).values_list('tvseries__id', flat=True)
            else: rated_ids = Rating.objects.filter(user=request.user, score__gt=0, movie__isnull=False).values_list('movie__id', flat=True)
            base_queryset = base_queryset.exclude(id__in=rated_ids)

        if selected_genres and hasattr(base_queryset.model, 'tmdb_genre'):
            genre_q = Q()
            for genre in selected_genres:
                if genre == '정보 없음': genre_q |= (Q(tmdb_genre__isnull=True) | Q(tmdb_genre='') | Q(tmdb_genre='None') | Q(tmdb_genre='정보 없음'))
                else:
                    synonyms = GENRE_SYNONYMS.get(genre, [genre])
                    q = Q()
                    for syn in synonyms:
                        q |= Q(tmdb_genre__icontains=syn)
                        if hasattr(base_queryset.model, 'imdb_genre'): q |= Q(imdb_genre__icontains=syn)
                    genre_q |= q
            base_queryset = base_queryset.filter(genre_q)

        if selected_otts and hasattr(base_queryset.model, 'tmdb_streaming_providers'):
            ott_q = Q()
            for ott in selected_otts: ott_q |= Q(tmdb_streaming_providers__icontains=ott)
            base_queryset = base_queryset.filter(ott_q)

        if selected_ratings and hasattr(base_queryset.model, 'tmdb_certification_kr'):
            rating_q = Q()
            for r_val in selected_ratings:
                if r_val == 'ALL': rating_q |= (Q(tmdb_certification_kr__in=['ALL', 'All', '전체', 'G']) | Q(tmdb_certification_kr__icontains='전체') | Q(tmdb_certification_us__in=['G', 'TV-G', 'TV-Y', 'TV-Y7']))
                elif r_val == '12': rating_q |= (Q(tmdb_certification_kr__icontains='12') | Q(tmdb_certification_us__in=['PG', 'TV-PG']))
                elif r_val == '15': rating_q |= (Q(tmdb_certification_kr__icontains='15') | Q(tmdb_certification_us__in=['PG-13', 'TV-14']))
                elif r_val == '19': rating_q |= (Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | Q(tmdb_certification_kr__icontains='청불') | Q(tmdb_certification_us__in=['R', 'NC-17', 'TV-MA']))
                elif r_val == '정보 없음': rating_q |= (Q(tmdb_certification_kr__in=['', '정보 없음', '미등급', 'None']) | Q(tmdb_certification_kr__isnull=True))
            base_queryset = base_queryset.filter(rating_q)

        if selected_countries and hasattr(base_queryset.model, 'tmdb_production_country_kr'):
            country_q = Q()
            for c in selected_countries:
                if c == '정보 없음': country_q |= (Q(tmdb_production_country_kr__isnull=True) | Q(tmdb_production_country_kr='') | Q(tmdb_production_country_kr='None') | Q(tmdb_production_country_kr='정보 없음'))
                else:
                    target_codes = [k for k, v in COUNTRY_KR_MAP.items() if v == c or k == c]
                    target_codes.append(c)
                    sub_q = Q()
                    for tc in set(target_codes):
                        sub_q |= Q(tmdb_production_country_kr__icontains=tc)
#                        if hasattr(base_queryset.model, 'tmdb_production_country_eng'): sub_q |= Q(tmdb_production_country_eng__icontains=tc)   #국가명으로 검색하지 않고 코드로만 반영
                        if hasattr(base_queryset.model, 'tmdb_production_country_code'): sub_q |= Q(tmdb_production_country_code__icontains=tc)
                    country_q |= sub_q
            base_queryset = base_queryset.filter(country_q)


        # =====================================================================
        # 💡 [수정] 1. 평점 슬라이더 필터 (0~10점, 0점은 무평점도 포함)
        # =====================================================================
        try:
            r_min = float(rating_min)
            r_max = float(rating_max)
            # 0~10 전체를 당긴 게 아닐 때만 작동!
            if r_min != 0.0 or r_max != 10.0:
                if hasattr(base_queryset.model, 'imdb_rating'):
                    rating_q = Q(imdb_rating__gte=r_min, imdb_rating__lte=r_max)
                    # 💡 왼쪽 손잡이가 0점에 있으면, 아예 평점이 없는(Null) 작품도 0점으로 간주해 포함시킵니다!
                    if r_min == 0.0:
                        rating_q |= Q(imdb_rating__isnull=True)
                        
                    base_queryset = base_queryset.filter(rating_q)
        except ValueError:
            pass

        # =====================================================================
        # 💡 [추가] 2. 기간 슬라이더 필터
        # =====================================================================
        if period_min_idx != 0 or period_max_idx != 8:
            now = timezone.now().date()
            days_map = [36500, 15*365, 10*365, 5*365, 3*365, 2*365, 365, 180, 90]
            start_date = now - timedelta(days=days_map[period_min_idx])
            end_date = now + timedelta(days=3650) if period_max_idx == 8 else now - timedelta(days=days_map[period_max_idx])
            
            if content_type == 'tv' and hasattr(base_queryset.model, 'first_air_date'):
                base_queryset = base_queryset.filter(first_air_date__range=[start_date, end_date])
            elif hasattr(base_queryset.model, 'tmdb_release_date'):
                base_queryset = base_queryset.filter(tmdb_release_date__range=[start_date, end_date])

        # =====================================================================
        # 💡 [추가] 3. 관람등급 슬라이더 필터 (US 오차 방어막 완벽 적용)
        # =====================================================================
        if age_min_idx != 0 or age_max_idx != 3:
            age_map = ['ALL', '12', '15', '19']
            allowed_ratings = age_map[age_min_idx : age_max_idx + 1]
            
            if hasattr(base_queryset.model, 'tmdb_certification_kr'):
                rating_q = Q()
                # 💡 [핵심 방어막] 한국 등급 정보가 완전히 비어있을 때만 미국 등급을 참고하도록 강제!
                missing_kr = Q(tmdb_certification_kr__in=['', '정보 없음', '미등급', 'None']) | Q(tmdb_certification_kr__isnull=True)
                
                if 'ALL' in allowed_ratings:
                    rating_q |= (Q(tmdb_certification_kr__in=['ALL', 'All', '전체', 'G']) | Q(tmdb_certification_kr__icontains='전체') | (missing_kr & Q(tmdb_certification_us__in=['G', 'TV-G', 'TV-Y', 'TV-Y7'])))
                if '12' in allowed_ratings:
                    rating_q |= (Q(tmdb_certification_kr__icontains='12') | (missing_kr & Q(tmdb_certification_us__in=['PG', 'TV-PG'])))
                if '15' in allowed_ratings:
                    rating_q |= (Q(tmdb_certification_kr__icontains='15') | (missing_kr & Q(tmdb_certification_us__in=['PG-13', 'TV-14'])))
                if '19' in allowed_ratings:
                    rating_q |= (Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | Q(tmdb_certification_kr__icontains='청불') | (missing_kr & Q(tmdb_certification_us__in=['R', 'NC-17', 'TV-MA'])))
                
                base_queryset = base_queryset.filter(rating_q)


    # 5. 💡 정렬 및 페이지네이션
    sort_by = request.GET.get('sort', 'votes_desc')

    # 🚀 [추가됨] "내 평점순" 정렬 로직 (DB에서 직접 유저 평점 매핑 후 정렬)
    if sort_by in ['my_desc', 'my_asc'] and request.user.is_authenticated:
        if content_type == 'tv':
            user_rating_subquery = Rating.objects.filter(user=request.user, tvseries__id=OuterRef('pk')).values('score')
        else:
            user_rating_subquery = Rating.objects.filter(user=request.user, movie__id=OuterRef('pk')).values('score')
            
        # 로그인한 유저의 점수표를 가상(my_score_db)으로 붙여줍니다. (평가 안 했으면 0점)
        base_queryset = base_queryset.annotate(
            my_score_db=Coalesce(Subquery(user_rating_subquery[:1]), 0, output_field=IntegerField())
        )
        
        if sort_by == 'my_desc':
            # 내 평점 높은 순 ▼
            base_queryset = base_queryset.order_by('-my_score_db', '-imdb_vote_count', '-id')
        else:
            # 내 평점 낮은 순 ▲ (단, 0점인 미평가 작품들은 맨 뒤로 밀어내고 평가한 작품들만 줄세우기)
            base_queryset = base_queryset.annotate(
                has_score=Case(When(my_score_db__gt=0, then=Value(1)), default=Value(0), output_field=IntegerField())
            ).order_by('-has_score', 'my_score_db', '-imdb_vote_count', '-id')

    # 기존 정렬 로직 (IMDb 및 평가수)
    else:
        if sort_by == 'imdb_desc' and hasattr(base_queryset.model, 'imdb_rating'): 
            base_queryset = base_queryset.order_by('-imdb_rating', '-imdb_vote_count', '-id')
        elif sort_by == 'imdb_asc' and hasattr(base_queryset.model, 'imdb_rating'): 
            base_queryset = base_queryset.order_by('imdb_rating', '-imdb_vote_count', '-id')
        elif sort_by == 'votes_asc' and hasattr(base_queryset.model, 'imdb_vote_count'): 
            base_queryset = base_queryset.order_by('imdb_vote_count', '-id')
        elif hasattr(base_queryset.model, 'imdb_vote_count'): 
            base_queryset = base_queryset.order_by('-imdb_vote_count', '-id')
        else: 
            base_queryset = base_queryset.order_by('-id')

    # 💡 [복구 완료] 실수로 잘려나갔던 페이지 처리 부분 복구!
    paginator = Paginator(base_queryset, 15)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)


    # 6. 💡 로그인 유저 데이터 매핑
    if request.user.is_authenticated:
        items = list(page_obj)  # 💡 [핵심 해결] 페이지 객체를 리스트로 단단하게 묶어서 100% 정확하게 매핑!
        if content_type == 'tv' and hasattr(Rating, 'tvseries'):
            user_ratings = Rating.objects.filter(user=request.user, tvseries__in=items).select_related('tvseries')
            rating_dict = {r.tvseries.id: int(r.score) for r in user_ratings if r.score}
            
            watchlists = Watchlist.objects.filter(user=request.user, tvseries__in=items).select_related('tvseries')
            watchlist_set = set(w.tvseries.id for w in watchlists)
        else:
            user_ratings = Rating.objects.filter(user=request.user, movie__in=items).select_related('movie')
            rating_dict = {r.movie.id: int(r.score) for r in user_ratings if r.score}
            
            watchlists = Watchlist.objects.filter(user=request.user, movie__in=items).select_related('movie')
            watchlist_set = set(w.movie.id for w in watchlists)
    else:
        rating_dict = {}
        watchlist_set = set()

    for item in page_obj:
        item.my_score = rating_dict.get(item.id, 0)
        item.is_watchlisted = item.id in watchlist_set
        if not hasattr(item, 'tmdb_title'): item.tmdb_title = getattr(item, 'name', '') or getattr(item, 'tmdb_name', '') or getattr(item, 'title', '제목 없음')
        if not hasattr(item, 'tmdb_poster_url') and hasattr(item, 'poster_url'): item.tmdb_poster_url = item.poster_url

        full_genre_str = get_display_genre(getattr(item, 'tmdb_genre', None), getattr(item, 'imdb_genre', None))
        if full_genre_str and full_genre_str != '정보 없음':
            g_list = [g.strip() for g in full_genre_str.split(',') if g.strip()]
            item.short_genre = f'{g_list[0]}+' if len(g_list) > 1 else g_list[0]
        else: item.short_genre = '정보 없음'

        country_str = getattr(item, 'tmdb_production_country_kr', None) or getattr(item, 'tmdb_production_country_eng', None) or getattr(item, 'tmdb_production_country_code', None) or ''
        if country_str and str(country_str).strip() and str(country_str).strip() not in ['None', '정보 없음', '국가 미상', '']:
            c_list = [c.strip() for c in str(country_str).split(',') if c.strip()]
            mapped_c = [COUNTRY_KR_MAP.get(c, c) for c in c_list]
            
            # 🚀 [핵심 수정] 여기에 2개 이상일 때 '+' 기호를 붙이는 로직이 빠져있었습니다!
            item.short_country = f"{mapped_c[0]}+" if len(mapped_c) > 1 else mapped_c[0]
        else: item.short_country = '국가 미상'

    matched_people = {}
    
    if search_query:
        # 💡 all_list 최상단에서 이미 cruise -> 크루즈 변환 및 regex_str 생성을 마쳤으므로
        # 여기서는 그 만들어진 정규식과 q_clean을 그대로 쓰기만 하면 됩니다!
        
        def extract_people(queryset):
            # 🚀 [핵심] 상위 대작 50개만 스캔하여 속도 쾌속 + 인지도순 탐색
            for item in queryset[:50]: 
                item_votes = getattr(item, 'imdb_vote_count', 0) or 0
                
                # 🎭 [배우 찾기]
                actors = getattr(item, 'tmdb_actor_details', [])
                if isinstance(actors, str):
                    try: actors = json.loads(actors)
                    except Exception: actors = []
                if isinstance(actors, list):
                    for actor in actors:
                        actor_name = str(actor.get('name', '')).replace(' ', '').lower()
                        actor_original = str(actor.get('original_name', '')).replace(' ', '').lower()
                        
                        # 🚀 [핵심] 원본어(cruise)와 치환어(크루즈) 중 하나라도 걸리면 무조건 캐치!
                        if any(kw in actor_name or (kw and kw in actor_original) for kw in search_keywords):
                            pid = actor.get('id')
                            if pid:
                                if pid not in matched_people:
                                    matched_people[pid] = {'id': pid, 'name': actor.get('name'), 'profile_url': actor.get('profile_url', ''), 'type': '배우', 'score': 0}
                                matched_people[pid]['score'] += item_votes
                
                # 🎬 [감독 찾기]
                director = str(getattr(item, 'tmdb_director', '') or '')
                dir_clean = director.replace(' ', '').lower()
                if any(kw in dir_clean for kw in search_keywords):
                    did = getattr(item, 'tmdb_director_id', None)
                    if did:
                        if did not in matched_people:
                            matched_people[did] = {'id': did, 'name': director, 'profile_url': getattr(item, 'tmdb_director_image_url', ''), 'type': '감독', 'score': 0}
                        matched_people[did]['score'] += item_votes
                
                # ✍️ [각본가 찾기]
                writer = str(getattr(item, 'tmdb_screenwriter', '') or '')
                wrt_clean = writer.replace(' ', '').lower()
                if any(kw in wrt_clean for kw in search_keywords):
                    wid = getattr(item, 'tmdb_screenwriter_id', None)
                    if wid:
                        if wid not in matched_people:
                            matched_people[wid] = {'id': wid, 'name': writer, 'profile_url': '', 'type': '각본가', 'score': 0}
                        matched_people[wid]['score'] += item_votes

        # 🚀 [핵심] 팝업창과 100% 동일한 '정규식 완전체 조건'을 사용하여 DB를 훑습니다.
        m_cond_p = Q(tmdb_title__iregex=regex_str)
        if hasattr(Movie, 'translated_title'): m_cond_p |= Q(translated_title__iregex=regex_str)
        if hasattr(Movie, 'tmdb_original_title'): m_cond_p |= Q(tmdb_original_title__iregex=regex_str)
        if hasattr(Movie, 'tmdb_actors'): m_cond_p |= Q(tmdb_actors__iregex=regex_str)
        if hasattr(Movie, 'tmdb_actor_details'): m_cond_p |= Q(tmdb_actor_details__iregex=regex_str)
        if hasattr(Movie, 'tmdb_director'): m_cond_p |= Q(tmdb_director__iregex=regex_str)

        t_cond_p = Q(tmdb_title__iregex=regex_str)
        if hasattr(TvSeries, 'translated_title'): t_cond_p |= Q(translated_title__iregex=regex_str)
        if hasattr(TvSeries, 'tmdb_original_title'): t_cond_p |= Q(tmdb_original_title__iregex=regex_str)
        if hasattr(TvSeries, 'tmdb_actors'): t_cond_p |= Q(tmdb_actors__iregex=regex_str)
        if hasattr(TvSeries, 'tmdb_actor_details'): t_cond_p |= Q(tmdb_actor_details__iregex=regex_str)
        if hasattr(TvSeries, 'tmdb_director'): t_cond_p |= Q(tmdb_director__iregex=regex_str)

        # 💡 투표수 내림차순(인기 대작 우선)으로 정렬하여 탐색 함수로 넘김
        extract_people(Movie.objects.filter(m_cond_p).order_by('-imdb_vote_count', '-id'))
        extract_people(TvSeries.objects.filter(t_cond_p).order_by('-imdb_vote_count', '-id'))

    # 🚀 최종 추출된 인물 리스트를 누적 점수(투표수) 기준으로 내림차순 정렬 후 15명 컷!
    sorted_people = sorted(matched_people.values(), key=lambda x: x['score'], reverse=True)
    people_list = sorted_people[:15]

    context = {
        'movies': page_obj, 'current_type': content_type,

        # 💡 [핵심 수정] 탭에 표시되는 총 개수에서도 IMDb ID가 없는 불량품은 빼고 셉니다!
        'movie_total_count': Movie.objects.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id='')).count(), 
        'tv_total_count': TvSeries.objects.exclude(Q(tmdb_imdb_id__isnull=True) | Q(tmdb_imdb_id='')).count(),

        'sort_by': sort_by, 'search_query': search_query, 'filter_submitted': filter_submitted,
        'genres_list': genres_list, 'selected_genres': selected_genres,
        'otts_list': otts_list, 'selected_otts': selected_otts,
        'selected_ratings': selected_ratings,
        'countries_list': countries_list, 'selected_countries': selected_countries,
        'exclude_rated': exclude_rated, 'exclude_no_imdb': exclude_no_imdb,
        'exclude_no_rating': exclude_no_rating, 'exclude_low_rating': exclude_low_rating,
        'exclude_low_votes': exclude_low_votes, 'exclude_doc': exclude_doc,
        'exclude_short': exclude_short, 'exclude_unreleased': exclude_unreleased,
        'people': people_list,
    }
    return render(request, 'movie/all_list.html', context)

# 💡 [영화 상세 페이지 뷰]
def movie_detail(request, movie_id):
    # 🚀 스마트 안전망: 만약 접속한 ID가 영화 DB에 없고 TV DB에 있다면 자동으로 튕겨줍니다.
    if (not Movie.objects.filter(id=movie_id).exists() and TvSeries.objects.filter(id=movie_id).exists()):
        return redirect('tv_detail', series_id=movie_id)

    movie = get_object_or_404(Movie, id=movie_id)
    movie.display_genre = get_display_genre(movie.tmdb_genre, movie.imdb_genre)
    movie.display_date = get_display_date(movie.tmdb_release_date, movie.imdb_release_date)
    movie.display_runtime = get_display_runtime(movie.tmdb_runtime, movie.imdb_runtime)

    # 🚀 [추가] 언어 코드를 한글로 1줄 컷 변환! (사전에 없으면 대문자로 변환, 값 없으면 언어 미상)
    movie.display_language = LANGUAGE_KR_MAP.get(movie.tmdb_original_language, str(movie.tmdb_original_language).upper() if movie.tmdb_original_language else '언어 미상')

    # ==========================================
    # 2. TMDB 추천/유사작 DB 보유 여부 확인 로직 (💡 완전 엄격 매칭!)
    # ==========================================
    enriched_recommendations = []
    
    if movie.tmdb_recommended_movies: 
        for rec in movie.tmdb_recommended_movies:
            rec_title = rec.get('title')
            rec_year = str(rec.get('release_date') or '')[:4]
            rec_tmdb_id = rec.get('id')  # TMDB 고유 ID
            
            matched_movie = None
            
            # 🚀 [1차 완벽 매칭] 무조건 TMDB 고유 ID로만 찾습니다! (동명이작 원천 차단)
            if rec_tmdb_id:
                matched_movie = Movie.objects.filter(tmdb_id=rec_tmdb_id).first()
            
            # 🚀 [2차 엄격 매칭] 구형 API라 ID가 없다면, 반드시 '제목'과 '연도'가 둘 다 일치할 때만 연결!
            if not matched_movie and rec_year:
                matched_movie = Movie.objects.filter(
                    tmdb_title=rec_title, 
                    tmdb_release_date__startswith=rec_year
                ).first()
            # 🚨 연도가 안 맞는데 이름만 같다고 억지로 물려버리던 위험한 코드는 완전히 삭제했습니다!
            
            raw_rec_genre = rec.get('genre', '')
            if isinstance(raw_rec_genre, list): raw_rec_genre = ', '.join(raw_rec_genre)
                
            if matched_movie: full_genre_str = get_display_genre(getattr(matched_movie, 'tmdb_genre', None), getattr(matched_movie, 'imdb_genre', None))
            else: full_genre_str = get_display_genre(raw_rec_genre, '')

            if full_genre_str and full_genre_str != '정보 없음':
                g_list = [g.strip() for g in full_genre_str.split(',') if g.strip()]
                first_genre = g_list[0]
                if '&' in first_genre: display_genre = f"{first_genre.split('&')[0].strip()}+"
                else: display_genre = f"{first_genre}+" if len(g_list) > 1 else first_genre
            else:
                display_genre = '정보 없음'

            display_country = rec.get('country', '국가 미상')
            my_rec_score = None

            if matched_movie:
                if matched_movie.tmdb_production_country_kr:
                    c_list = [c.strip() for c in matched_movie.tmdb_production_country_kr.split(',')]
                    display_country = f"{c_list[0]}+" if len(c_list) > 1 else c_list[0]
                
                if request.user.is_authenticated:
                    user_rating = Rating.objects.filter(user=request.user, movie=matched_movie).first()
                    if user_rating: my_rec_score = user_rating.score
                
                try: db_imdb_score = float(matched_movie.imdb_rating or 0.0)
                except Exception: db_imdb_score = 0.0
                try: db_imdb_votes = int(matched_movie.imdb_vote_count or 0)
                except Exception: db_imdb_votes = 0
            else:
                db_imdb_score = 0.0; db_imdb_votes = 0

            enriched_recommendations.append({
                'title': rec_title, 'poster_url': rec.get('poster_url'),
                'release_date': rec_year if rec_year else '연도미상',
                'genre': display_genre, 'country': display_country,
                'rating': rec.get('rating', 0.0), 'vote_count': rec.get('vote_count', 0),
                'my_score': my_rec_score, 'is_in_db': bool(matched_movie),              
                'local_id': matched_movie.id if matched_movie else None, 'movie_obj': matched_movie if matched_movie else None,
                'imdb_rating': db_imdb_score, 'imdb_vote_count': db_imdb_votes,
            })

    my_score = 0
    movie_review = ""
    my_is_public = True 
    
    if request.user.is_authenticated:
        my_rating = Rating.objects.filter(user=request.user, movie=movie).first()
        if my_rating:
            my_score = my_rating.score
            movie_review = my_rating.review
            my_is_public = my_rating.is_public

    omo_stats = Rating.objects.filter(movie=movie).aggregate(avg_score=Avg('score'), total_votes=Count('id'))
    omo_avg_score = round(omo_stats['avg_score'], 1) if omo_stats['avg_score'] else 0.0
    omo_vote_count = omo_stats['total_votes']

    # 💡 [.select_related('user') 추가] 한 번의 DB 왕복으로 리뷰와 유저 닉네임을 싹 다 가져옵니다!
    public_reviews_query = Rating.objects.filter(movie=movie, is_public=True).exclude(review__isnull=True).exclude(review__exact='').select_related('user')
    total_reviews_count = public_reviews_query.count()
    public_reviews = public_reviews_query.order_by('-updated_at')[:3]

    # =========================================================
    # 💡 [수정] 예고편 오류 카운트 및 중복 검증 로직 (시리즈)
    # =========================================================
    if not request.session.session_key:
        request.session.create()
    
    # 영화/시리즈 분기 (movie_detail은 movie, tv_detail은 tvseries로 변수명 맞춰주세요)
    target_obj = movie # (tv_detail에서는 target_obj = series 로 변경)
    
    active_report_count = TrailerReport.objects.filter(movie=target_obj, is_resolved=False).count() # (tv_detail에선 tvseries=target_obj)
    
    has_reported = False
    if request.user.is_authenticated:
        has_reported = TrailerReport.objects.filter(movie=target_obj, user=request.user, is_resolved=False).exists()
    else:
        has_reported = TrailerReport.objects.filter(movie=target_obj, session_key=request.session.session_key, is_resolved=False).exists()
        
    # context에 'active_report_count': active_report_count, 'has_reported': has_reported 를 넘겨줍니다.

    context = {
        'movie': movie, 'recommendations': enriched_recommendations,
        'my_score': my_score, 'movie_review': movie_review, 'my_is_public': my_is_public,
        'public_reviews': public_reviews, 'total_reviews_count': total_reviews_count,
        'omo_avg_score': omo_avg_score, 'omo_vote_count': omo_vote_count, 
    }
    return render(request, "movie/movie_detail.html", context)

# 💡 [영화 전체 감상평 더보기 뷰]
def movie_reviews_all(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    all_reviews_list = Rating.objects.filter(movie=movie, is_public=True).exclude(review__isnull=True).exclude(review__exact='').order_by('-updated_at')
    total_count = all_reviews_list.count()
    paginator = Paginator(all_reviews_list, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    context = {'movie': movie, 'all_reviews': page_obj, 'total_count': total_count}
    return render(request, 'movie/movie_reviews_all.html', context)

# 💡 [영화 평가/감상평 저장 비동기 뷰]
@login_required
@require_POST
def rate_movie(request, movie_id):
    try:
        content_type = request.POST.get('type', request.GET.get('type', 'movie')).lower()
        if content_type == 'tv' or not Movie.objects.filter(id=movie_id).exists():
            if TvSeries.objects.filter(id=movie_id).exists():
                return rate_tv(request, series_id=movie_id)

        movie = get_object_or_404(Movie, id=movie_id)
        
        score = request.POST.get('score', 0)
        review_text = request.POST.get('review', '')
        is_public = str(request.POST.get('is_public', 'true')).lower() in ['true', 'on', '1', 'yes']

        try: score = int(score)
        except ValueError: score = 0

        is_deleted = False
        current_score = 0
        current_review = ''
        current_is_public = True

        if score == 0:
            Rating.objects.filter(user=request.user, movie=movie).delete()
            is_deleted = True
        else:
            rating, created = Rating.objects.update_or_create(
                user=request.user, movie=movie,
                defaults={'score': score, 'review': review_text, 'is_public': is_public}
            )
            current_score = int(rating.score)
            current_review = rating.review
            current_is_public = rating.is_public

        # 💡 [통계 재계산 및 실시간 화면 업데이트(AJAX) 전송 데이터 포장]
        omo_stats = Rating.objects.filter(movie=movie).aggregate(avg_score=Avg('score'), total_votes=Count('id'))
        omo_avg_score = round(omo_stats['avg_score'], 1) if omo_stats['avg_score'] else 0.0
        omo_vote_count = omo_stats['total_votes']
        
        public_reviews_qs = Rating.objects.filter(movie=movie, is_public=True).exclude(review__isnull=True).exclude(review__exact='')
        total_reviews_count = public_reviews_qs.count()
        top_reviews = [{'username': r.user.username, 'score': int(r.score), 'review': r.review, 'date': r.updated_at.strftime('%Y.%m.%d')} for r in public_reviews_qs.order_by('-updated_at')[:3]]

        return JsonResponse({
            'status': 'success', 'current_score': current_score, 'review': current_review,          
            'is_public': current_is_public, 'is_deleted': is_deleted,
            'omo_avg_score': omo_avg_score, 'omo_vote_count': omo_vote_count,
            'total_reviews_count': total_reviews_count, 'top_reviews': top_reviews
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

# 💡 [TV 시리즈 상세 페이지 뷰]
def tv_detail(request, series_id):
    series = get_object_or_404(TvSeries, id=series_id)
    series.display_genre = get_display_genre(getattr(series, 'tmdb_genre', ''), getattr(series, 'imdb_genre', ''))
    series.display_date = get_display_date(getattr(series, 'tmdb_release_date', None) or getattr(series, 'first_air_date', None), getattr(series, 'imdb_release_date', ''))
    series.display_runtime = get_display_runtime(getattr(series, 'tmdb_runtime', 0), getattr(series, 'imdb_runtime', 0))

    # 🚀 [추가] 언어 코드를 한글로 1줄 컷 변환!
    series.display_language = LANGUAGE_KR_MAP.get(series.tmdb_original_language, str(series.tmdb_original_language).upper() if series.tmdb_original_language else '언어 미상')

    # 2. TMDB 추천/유사 TV 시리즈 DB 보유 여부 확인
    enriched_recommendations = []
    rec_list = getattr(series, 'tmdb_recommended_series', None) or getattr(series, 'tmdb_recommended_movies', None)

    if rec_list:
      for rec in rec_list:
        rec_title = rec.get('title') or rec.get('name')
        rec_year = str(rec.get('release_date') or rec.get('first_air_date') or '')[:4]
        rec_tmdb_id = rec.get('id')  # TMDB 고유 ID
      
        matched_series = None
      
        # 🚀 [1차 완벽 매칭] 무조건 TMDB 고유 ID로 다이렉트 검색!
        if rec_tmdb_id:
            matched_series = TvSeries.objects.filter(tmdb_id=rec_tmdb_id).first()

        # 🚀 [2차 엄격 매칭] 구형 API라 ID가 없다면, '제목'과 '연도'가 모두 일치할 때만 연결!
        if not matched_series and rec_year:
            matched_series = TvSeries.objects.filter(
                tmdb_title=rec_title, tmdb_release_date__startswith=rec_year
            ).first()
        # 🚨 이름만 겹친다고 다른 작품을 연결하는 로직 원천 차단 완료!

        raw_rec_genre = rec.get('genre', '')
        if isinstance(raw_rec_genre, list): raw_rec_genre = ', '.join(raw_rec_genre)
          
        if matched_series: full_genre_str = get_display_genre(getattr(matched_series, 'tmdb_genre', None), getattr(matched_series, 'imdb_genre', None))
        else: full_genre_str = get_display_genre(raw_rec_genre, '')

        if full_genre_str and full_genre_str != '정보 없음':
            g_list = [g.strip() for g in full_genre_str.split(',') if g.strip()]
            first_genre = g_list[0]
            if '&' in first_genre: display_genre = f"{first_genre.split('&')[0].strip()}+"
            else: display_genre = f"{first_genre}+" if len(g_list) > 1 else first_genre
        else: display_genre = '정보 없음'

        display_country = rec.get('country', '국가 미상')
        my_rec_score = None

        if matched_series:
          if getattr(matched_series, 'tmdb_production_country_kr', ''):
            c_list = [c.strip() for c in matched_series.tmdb_production_country_kr.split(',')]
            display_country = f"{c_list[0]}+" if len(c_list) > 1 else c_list[0]

          if request.user.is_authenticated:
            user_rating = Rating.objects.filter(user=request.user, tvseries=matched_series).first()
            if user_rating: my_rec_score = user_rating.score
            
          try: db_imdb_score = float(getattr(matched_series, 'imdb_rating', 0.0) or 0.0)
          except Exception: db_imdb_score = 0.0
          try: db_imdb_votes = int(getattr(matched_series, 'imdb_vote_count', 0) or 0)
          except Exception: db_imdb_votes = 0
        else:
          db_imdb_score = 0.0; db_imdb_votes = 0

        enriched_recommendations.append({
            'title': rec_title, 'poster_url': rec.get('poster_url'),
            'release_date': rec_year if rec_year else '연도미상',
            'genre': display_genre, 'country': display_country,
            'rating': rec.get('rating', 0.0), 'vote_count': rec.get('vote_count', 0),
            'my_score': my_rec_score, 'is_in_db': bool(matched_series),
            'local_id': matched_series.id if matched_series else None,
            'series_obj': matched_series if matched_series else None,
            'imdb_rating': db_imdb_score, 'imdb_vote_count': db_imdb_votes,
        })

    my_score = 0
    series_review = ''
    my_is_public = True

    if request.user.is_authenticated:
      my_rating = Rating.objects.filter(user=request.user, tvseries=series).first()
      if my_rating:
        my_score = my_rating.score
        series_review = my_rating.review
        my_is_public = my_rating.is_public

    omo_stats = Rating.objects.filter(tvseries=series).aggregate(avg_score=Avg('score'), total_votes=Count('id'))
    omo_avg_score = round(omo_stats['avg_score'], 1) if omo_stats['avg_score'] else 0.0
    omo_vote_count = omo_stats['total_votes']

    # 💡 [.select_related('user') 추가] 한 번의 DB 왕복으로 리뷰와 유저 닉네임을 싹 다 가져옵니다!
    public_reviews_query = Rating.objects.filter(tvseries=series, is_public=True).exclude(review__isnull=True).exclude(review__exact='').select_related('user')
    total_reviews_count = public_reviews_query.count()
    public_reviews = public_reviews_query.order_by('-updated_at')[:3]

    # =========================================================
    # 💡 [수정] 예고편 오류 카운트 및 중복 검증 로직 (시리즈)
    # =========================================================
    if not request.session.session_key:
        request.session.create()
    
    # 영화/시리즈 분기 (movie_detail은 movie, tv_detail은 tvseries로 변수명 맞춰주세요)
    target_obj = series # (tv_detail에서는 target_obj = series 로 변경)
    
    active_report_count = TrailerReport.objects.filter(tvseries=target_obj, is_resolved=False).count() # (tv_detail에선 tvseries=target_obj)
      
    has_reported = False
    if request.user.is_authenticated:
        has_reported = TrailerReport.objects.filter(tvseries=target_obj, user=request.user, is_resolved=False).exists()
    else:
        has_reported = TrailerReport.objects.filter(tvseries=target_obj, session_key=request.session.session_key, is_resolved=False).exists()
          
    # context에 'active_report_count': active_report_count, 'has_reported': has_reported 를 넘겨줍니다.

    context = {
        'movie': series, 'series': series, 'recommendations': enriched_recommendations,
        'my_score': my_score, 'movie_review': series_review, 'my_is_public': my_is_public,
        'public_reviews': public_reviews, 'total_reviews_count': total_reviews_count,
        'omo_avg_score': omo_avg_score, 'omo_vote_count': omo_vote_count, 'is_tv': True, 
    }
    return render(request, 'movie/tv_detail.html', context)

# 💡 [TV 시리즈 전체 감상평 더보기 뷰]
def tv_reviews_all(request, series_id):
  series = get_object_or_404(TvSeries, id=series_id)
  all_reviews_list = Rating.objects.filter(tvseries=series, is_public=True).exclude(review__isnull=True).exclude(review__exact='').order_by('-updated_at')
  total_count = all_reviews_list.count()
  paginator = Paginator(all_reviews_list, 10)
  page_number = request.GET.get('page', 1)
  page_obj = paginator.get_page(page_number)

  context = {'movie': series, 'series': series, 'all_reviews': page_obj, 'total_count': total_count, 'is_tv': True}
  return render(request, 'movie/movie_reviews_all.html', context)

# 💡 [TV 시리즈 평가/감상평 저장 비동기 뷰]
@login_required
@require_POST
def rate_tv(request, series_id):
    try:
        series = get_object_or_404(TvSeries, id=series_id)
        score = request.POST.get('score', 0)
        review_text = request.POST.get('review', '')
        is_public = str(request.POST.get('is_public', 'true')).lower() in ['true', 'on', '1', 'yes']

        try: score = int(score)
        except ValueError: score = 0

        is_deleted = False
        current_score = 0
        current_review = ''
        current_is_public = True

        if score == 0:
            Rating.objects.filter(user=request.user, tvseries=series).delete()
            is_deleted = True
        else:
            rating, created = Rating.objects.update_or_create(
                user=request.user, tvseries=series,
                defaults={'score': score, 'review': review_text, 'is_public': is_public},
            )
            current_score = int(rating.score)
            current_review = rating.review
            current_is_public = rating.is_public

        # 💡 [통계 재계산 및 실시간 화면 업데이트(AJAX) 전송 데이터 포장]
        omo_stats = Rating.objects.filter(tvseries=series).aggregate(avg_score=Avg('score'), total_votes=Count('id'))
        omo_avg_score = round(omo_stats['avg_score'], 1) if omo_stats['avg_score'] else 0.0
        omo_vote_count = omo_stats['total_votes']
        
        public_reviews_qs = Rating.objects.filter(tvseries=series, is_public=True).exclude(review__isnull=True).exclude(review__exact='')
        total_reviews_count = public_reviews_qs.count()
        top_reviews = [{'username': r.user.username, 'score': int(r.score), 'review': r.review, 'date': r.updated_at.strftime('%Y.%m.%d')} for r in public_reviews_qs.order_by('-updated_at')[:3]]

        return JsonResponse({
            'status': 'success', 'current_score': current_score, 'review': current_review,
            'is_public': current_is_public, 'is_deleted': is_deleted,
            'omo_avg_score': omo_avg_score, 'omo_vote_count': omo_vote_count,
            'total_reviews_count': total_reviews_count, 'top_reviews': top_reviews 
        })
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})



# ==============================================================================
# [SECTION 6] 인물(배우/스태프) 및 번역 뷰 (Actor, Crew & Translation Views)
# ==============================================================================
# 🌟 [통합 인물 상세 뷰] 배우 + 감독 + 각본가 완벽 지원 및 유저 데이터(tmdb_id) 연동
# ==============================================================================
def person_detail(request, person_id):
    # 💡 [핵심 보강 1] 모델 타입에 맞춘 ID 변환
    # 감독/각본가는 IntegerField이므로 int로, 배우(JSON) 검색은 str로 사용합니다.
    person_id_int = int(person_id)
    person_id_str = str(person_id).strip()
    
    # 💡 [속도 개선 1] 캐시(Cache) 적용: 변하지 않는 무거운 데이터(작품 목록, 기본 정보)는 통째로 기억!
    cache_key = f"person_detail_base_v2_{person_id_int}"
    cached_base = cache.get(cache_key)

    if cached_base:
        # 캐시에 있으면 DB나 외부 API를 거치지 않고 0.01초 만에 꺼내옵니다.
        person_data = cached_base['person_data']
        dir_m_list = cached_base['dir_m']
        dir_t_list = cached_base['dir_t']
        wrt_m_list = cached_base['wrt_m']
        wrt_t_list = cached_base['wrt_t']
        act_m_list = cached_base['act_m']
        act_t_list = cached_base['act_t']
    else:
        API_KEY = os.getenv("TMDB_API_KEY")

        # [1] TMDB API에서 인물 기본 정보 및 약력 가져오기 (한국어 + 영어 동시 호출)
        person_data = {}
        
        # 💡 [속도 개선 2] 멀티 스레딩: 한국어/영어 API를 순차적으로 기다리지 않고 '동시에' 호출하여 응답 시간 단축!
        def fetch_person_api(lang):
            try:
                res = requests.get(f"https://api.themoviedb.org/3/person/{person_id_int}?api_key={API_KEY}&language={lang}", timeout=3)
                if res.status_code == 200:
                    return res.json()
            except Exception:
                pass
            return {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_ko = executor.submit(fetch_person_api, "ko-KR")
            f_en = executor.submit(fetch_person_api, "en-US")
            person_data = f_ko.result()
            en_data = f_en.result()
            # 💡 영문 이름을 'english_name'이라는 키로 장착합니다!
            person_data['english_name'] = en_data.get('name', '')

        # [2] [연출/각본작] IntegerField 기반 100% 다이렉트 매칭 (초고속)
        dir_m_list = list(Movie.objects.filter(tmdb_director_id=person_id_int).order_by('-tmdb_release_date', '-id'))
        dir_t_list = list(TvSeries.objects.filter(tmdb_director_id=person_id_int).order_by('-tmdb_release_date', '-id'))
        wrt_m_list = list(Movie.objects.filter(tmdb_screenwriter_id=person_id_int).order_by('-tmdb_release_date', '-id'))
        wrt_t_list = list(TvSeries.objects.filter(tmdb_screenwriter_id=person_id_int).order_by('-tmdb_release_date', '-id'))

        # [3] [출연작] JSONField 내부 텍스트 매칭 검색
        acted_movie_qs = Movie.objects.filter(
            Q(tmdb_actor_details__icontains=f'"id": {person_id_str}') | 
            Q(tmdb_actor_details__icontains=f'"id":"{person_id_str}"')
        ).order_by('-tmdb_release_date', '-id')
        
        acted_tv_qs = TvSeries.objects.filter(
            Q(tmdb_actor_details__icontains=f'"id": {person_id_str}') | 
            Q(tmdb_actor_details__icontains=f'"id":"{person_id_str}"')
        ).order_by('-tmdb_release_date', '-id')

        # 💡 배역(캐릭터명) 추출 및 가짜 매칭 완벽 차단 함수
        def extract_character(queryset):
            results = []
            for item in queryset:
                char_name = ""
                details = getattr(item, 'tmdb_actor_details', None)
                
                # 문자열이면 파이썬 리스트/딕셔너리로 변환
                if isinstance(details, str):
                    try: details = json.loads(details)
                    except:
                        try: details = ast.literal_eval(details)
                        except: pass
                
                # 🚀 [추가된 핵심 방어막] 진짜 100% 일치하는 배우가 있는지 확인하는 스위치
                is_exact_match = False
                
                if isinstance(details, list):
                    for d in details:
                        # 💡 '12'와 '123'을 엄격하게 구분하여 완벽히 똑같을 때만 통과!
                        if isinstance(d, dict) and str(d.get('id', '')).strip() == person_id_str:
                            char_name = d.get('character', '')
                            is_exact_match = True
                            break
                
                # 🚀 억울하게 끌려온 엉뚱한 영화(부분 일치)는 버리고, 진짜 영화만 리스트에 담습니다!
                if is_exact_match:
                    item.character_name = char_name
                    results.append(item)
                    
            return results

        act_m_list = extract_character(acted_movie_qs)
        act_t_list = extract_character(acted_tv_qs)

        # 💡 [속도 개선 3] 무거운 쿼리셋 결과를 하루(24시간) 동안 메모리에 캐싱
        cache.set(cache_key, {
            'person_data': person_data, 
            'dir_m': dir_m_list, 'dir_t': dir_t_list,
            'wrt_m': wrt_m_list, 'wrt_t': wrt_t_list, 
            'act_m': act_m_list, 'act_t': act_t_list
        }, timeout=86400)

    # 💡 [캐시와 무관한 실시간 유저 데이터 동적 매핑 영역]
    # Rating과 Watchlist는 모델 설정상 내부 id가 아닌 'tmdb_id'를 외래키(to_field)로 사용합니다.
    def process_items(items, is_tv=False):
        processed = list(items)
        # 1. 쿼리셋/리스트에서 각각의 tmdb_id만 추출합니다.
        item_tmdb_ids = [item.tmdb_id for item in processed if item.tmdb_id]
        
        if request.user.is_authenticated and item_tmdb_ids:
            if is_tv:
                ratings = {r.tvseries_id: r.score for r in Rating.objects.filter(user=request.user, tvseries_id__in=item_tmdb_ids)}
                watchlists = set(Watchlist.objects.filter(user=request.user, tvseries_id__in=item_tmdb_ids).values_list('tvseries__id', flat=True))
            else:
                ratings = {r.movie_id: r.score for r in Rating.objects.filter(user=request.user, movie_id__in=item_tmdb_ids)}
                watchlists = set(Watchlist.objects.filter(user=request.user, movie_id__in=item_tmdb_ids).values_list('movie__id', flat=True))
        else:
            ratings, watchlists = {}, set()

        for item in processed:
            # 2. 템플릿에 보여주기 위해 매칭할 때도 내부 id가 아닌 tmdb_id를 사용합니다.
            item.my_score = ratings.get(item.tmdb_id, 0) 
            item.is_watchlisted = item.tmdb_id in watchlists
            item.is_tv = is_tv
            
            full_genre_str = getattr(item, 'tmdb_genre', '') or getattr(item, 'imdb_genre', '') or '정보 없음'
            if full_genre_str and full_genre_str != '정보 없음':
                g_list = [g.strip() for g in full_genre_str.split(',') if g.strip()]
                item.short_genre = f'{g_list[0]}+' if len(g_list) > 1 else g_list[0]
            else: item.short_genre = '정보 없음'
            
            country_str = getattr(item, 'tmdb_production_country_kr', '') or '정보 없음'
            if country_str and country_str != '정보 없음':
                c_list = [c.strip() for c in country_str.split(',')]
                item.short_country = f"{c_list[0]}+" if len(c_list) > 1 else c_list[0]
            else: item.short_country = '정보 없음'
            
            # 💡 연도 추출 (인물 타일에 표시하기 위해 추가)
            rel_date = getattr(item, 'tmdb_release_date', None) or getattr(item, 'first_air_date', None)
            item.release_year = str(rel_date)[:4] if rel_date else '----'
        return processed

    # ==============================================================================
    # 🚀 [핵심 보강 3 - 추가된 기능] 정확한 작품수 카운팅 및 노출 순서 자동 스위칭!
    # 기존 필터링 및 유저 평점 매핑 로직을 통과한 '최종 리스트'를 변수에 담습니다.
    # ==============================================================================
    dir_m = process_items(dir_m_list, is_tv=False)
    dir_t = process_items(dir_t_list, is_tv=True)
    wrt_m = process_items(wrt_m_list, is_tv=False)
    wrt_t = process_items(wrt_t_list, is_tv=True)
    act_m = process_items(act_m_list, is_tv=False)
    act_t = process_items(act_t_list, is_tv=True)

    # 💡 1. 템플릿 뱃지(Badge)에 표시할 분야별 정확한 개수 산출
    directed_count = len(dir_m) + len(dir_t)
    written_count = len(wrt_m) + len(wrt_t)
    acted_movie_count = len(act_m)
    acted_tv_count = len(act_t)
    acted_total_count = acted_movie_count + acted_tv_count

    # 💡 2. 노출 순서 스위칭 판별: 연출/각본 작품수의 합이 출연 작품수보다 많거나 같으면 감독(크루) 메인으로 판별!
    is_director_main = (directed_count + written_count) >= acted_total_count and (directed_count + written_count) > 0

    context = {
        'person': person_data,
        # 완벽하게 가공된 리스트 데이터를 HTML로 넘김
        'directed_movies': dir_m,
        'directed_tv': dir_t,
        'written_movies': wrt_m,
        'written_tv': wrt_t,
        'acted_movies': act_m,
        'acted_tv': act_t,
        
        # 💡 추가된 카운팅 숫자 & 스위칭용 불리언(True/False) 값 넘김
        'directed_count': directed_count,
        'written_count': written_count,
        'acted_movie_count': acted_movie_count,
        'acted_tv_count': acted_tv_count,
        'is_director_main': is_director_main,
    }
    
    return render(request, 'movie/person_detail.html', context)



# 💡 [초보자 안내] 작품 원제를 구글 번역 API에 연결하여 한글화해주는 지연 스크립트입니다.
def api_lazy_translate(request):
    ids = request.GET.getlist('ids')
    single_movie_id = request.GET.get('movie_id')
    single_series_id = request.GET.get('series_id')
    content_type = request.GET.get('type', 'movie') 
    
    if single_movie_id: ids.append(single_movie_id); content_type = 'movie'
    elif single_series_id: ids.append(single_series_id); content_type = 'tv'
    if not ids: return JsonResponse({'status': 'empty'})
    
    items = TvSeries.objects.filter(id__in=ids) if content_type == 'tv' else Movie.objects.filter(id__in=ids)
    translations = {}
    items_to_translate = []

    for m in items:
        # 💡 이미 한국 국가 작품이라면 구글에 물어보지 않고 패스!
        if m.tmdb_production_country_kr and str(m.tmdb_production_country_kr).strip().startswith('한국'): continue
        title = getattr(m, 'tmdb_title', getattr(m, 'name', ''))
        
        # 🚀 [숫자 전용 제목 방어막] 문자(영어/한글 등)가 없고 오직 '숫자와 기호'로만 이루어진 제목("1917", "2012!")은 번역 원천 차단!
        if title and re.match(r'^[\d\W_]+$', title):
            if getattr(m, 'translated_title', '') != "힣 번역 불가":
                m.translated_title = "힣 번역 불가"
                m.save(update_fields=['translated_title'])
            continue
            
        if title and re.search(r'[가-힣]', title):
            if hasattr(m, 'translated_title') and m.translated_title:
                m.translated_title = ''
                m.save(update_fields=['translated_title'])
            continue
            
        translated = getattr(m, 'translated_title', '')
        # 💡 "힣 번역 불가" 판정작은 두 번 다시 물어보지 않습니다.
        if translated == "힣 번역 불가": continue
        if translated and re.search(r'[가-힣]', translated): translations[str(m.id)] = translated
        else: items_to_translate.append(m)

    def build_response():
        response_data = {'status': 'success', 'translations': translations}
        target_id = single_series_id if content_type == 'tv' else single_movie_id
        if target_id and str(target_id) in translations: response_data['translated_title'] = translations[str(target_id)]
        return JsonResponse(response_data)

    if not items_to_translate: return build_response()

    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
    url = "https://translate.googleapis.com/translate_a/single"

    def fetch_trans(item):
        title = getattr(item, 'tmdb_title', getattr(item, 'name', ''))
        try:
            params = {"client": "gtx", "sl": "auto", "tl": "ko", "dt": "t", "q": title.lower()}
            res = session.get(url, params=params, timeout=3.0)
            if res.status_code == 200 and res.json()[0]:
                text = "".join([c[0] for c in res.json()[0] if c[0]]).strip()
                if re.search(r'[가-힣]', text) and text.lower() != title.lower(): return item, text
        except Exception: pass
        return item, None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_trans, items_to_translate)

    for item, text in results:
        item.refresh_from_db(fields=['translated_title'])
        db_title = getattr(item, 'translated_title', '')
        if text:
            item.translated_title = text
            translations[str(item.id)] = text
            item.save(update_fields=['translated_title'])
        else:
            if db_title and db_title != "힣 번역 불가" and re.search(r'[가-힣]', db_title): translations[str(item.id)] = db_title
            else:
                item.translated_title = "힣 번역 불가"
                item.save(update_fields=['translated_title'])
            
    return build_response()

# ==============================================================================
# [SECTION 7] 마이페이지, 유튜브 API 및 부가 기능 (My Page & Extra APIs)
# ==============================================================================
import json
from collections import defaultdict
from django.db.models import Avg
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Rating, Watchlist

@login_required
def my_page(request):
    user = request.user
    content_type = request.GET.get('type', 'movie').lower()
    active_tab = request.GET.get('active_tab', 'rated')

    # 1. 💡 콘텐츠 타입(영화/TV)에 따라 평점과 찜 내역 분리 조회
    if content_type == 'tv':
        ratings_list = list(Rating.objects.filter(user=user, score__gt=0, tvseries__isnull=False).select_related('tvseries').order_by('-updated_at', '-id'))
        watchlists = list(Watchlist.objects.filter(user=user, tvseries__isnull=False).select_related('tvseries').order_by('-created_at'))
        watchlist_ids = {w.tvseries_id for w in watchlists}
        user_ratings_map = {r.tvseries_id: (r.score, r.review) for r in ratings_list}
    else:
        ratings_list = list(Rating.objects.filter(user=user, score__gt=0, movie__isnull=False).select_related('movie').order_by('-updated_at', '-id'))
        watchlists = list(Watchlist.objects.filter(user=user, movie__isnull=False).select_related('movie').order_by('-created_at'))
        watchlist_ids = {w.movie_id for w in watchlists}
        user_ratings_map = {r.movie_id: (r.score, r.review) for r in ratings_list}

    total_runtime = 0
    genre_counts = defaultdict(int)
    keyword_counts = defaultdict(int) 
    actor_stats = {}    
    director_stats = {} 
    score_distribution = {str(float(i)): 0 for i in range(1, 11)} 

    # 🚨 [복구 완료] 평가한 작품들에 알맹이 정보(포스터, 제목 등)를 꽉꽉 채워줍니다!
    for r in ratings_list:
        obj = r.tvseries if content_type == 'tv' else r.movie
        if not obj: continue
        
        # HTML에서 쓸 수 있도록 movie_obj를 명시적으로 달아줍니다.
        r.movie_obj = obj
        r.movie_obj.my_score = r.score  # 💡 [핵심 추가] 파셜이 별점을 인식하도록 점수를 주입해 줍니다!
        
        # 화면 출력을 위한 예쁘게 가공된 데이터 생성
        obj.display_genre = get_display_genre(getattr(obj, 'tmdb_genre', ''), getattr(obj, 'imdb_genre', ''))
        obj.display_date = get_display_date(getattr(obj, 'tmdb_release_date', None), getattr(obj, 'imdb_release_date', ''))
        obj.display_runtime = get_display_runtime(getattr(obj, 'tmdb_runtime', 0), getattr(obj, 'imdb_runtime', 0))

        g_val = getattr(obj, 'display_genre', '') or ''
        obj.short_genre = g_val.split(',')[0].strip() + '+' if ',' in g_val else (g_val.split('/')[0].strip() + '+' if '/' in g_val else g_val)
        
        c_val = str(getattr(obj, 'tmdb_production_country_kr', '') or '')
        obj.short_country = c_val.split(',')[0].strip() + '+' if ',' in c_val else c_val

        if not hasattr(obj, 'tmdb_title'): 
            obj.tmdb_title = getattr(obj, 'name', '') or getattr(obj, 'tmdb_name', '') or getattr(obj, 'title', '제목 없음')

        # 통계용 데이터 수집
        safe_score = str(float(r.score))
        if safe_score not in score_distribution:
            score_distribution[safe_score] = 0
        score_distribution[safe_score] += 1
        
        # 🚀 [수정 완료] seasons_data(JSON)를 열어서 에피소드 수를 싹 다 긁어모읍니다!
        base_runtime = getattr(obj, 'tmdb_runtime', 0) or 0
        
        if content_type == 'tv':
            ep_count = 1
            seasons = getattr(obj, 'seasons_data', [])
            
            # JSON이 문자열로 저장되어 있을 경우를 대비한 안전장치
            if isinstance(seasons, str):
                try:
                    seasons = json.loads(seasons.replace("'", '"'))
                except Exception:
                    seasons = []
                    
            if isinstance(seasons, list) and seasons:
                total_eps = 0
                for season in seasons:
                    if isinstance(season, dict):
                        # 💡 스페셜 영상(season_number: 0)은 빼고 정규 시즌 에피소드만 합산!
                        if season.get('season_number', 1) > 0:
                            total_eps += int(season.get('episode_count', 0))
                
                if total_eps > 0:
                    ep_count = total_eps
                    
            total_runtime += (base_runtime * ep_count)
        else:
            total_runtime += base_runtime

        if getattr(obj, 'tmdb_genre', ''):
            for g in str(obj.tmdb_genre).split(','):
                if g.strip(): genre_counts[g.strip()] += 1

        if getattr(obj, 'tmdb_keywords', ''):
            for k in str(obj.tmdb_keywords).split(','):
                if k.strip(): keyword_counts[k.strip()] += 1
                
        dir_names = [d.strip() for d in str(getattr(obj, 'tmdb_director', '')).split(',') if d.strip()]
        dir_ids = [d.strip() for d in str(getattr(obj, 'tmdb_director_id', '')).split(',') if d.strip()]
        for idx, d_name in enumerate(dir_names):
            d_id = dir_ids[idx] if idx < len(dir_ids) else None
            if d_id and d_name:
                if d_id not in director_stats:
                    director_stats[d_id] = {'name': d_name, 'count': 0, 'id': d_id}
                director_stats[d_id]['count'] += 1

        actor_data = getattr(obj, 'tmdb_actor_details', [])
        if isinstance(actor_data, str):
            try: actor_data = json.loads(actor_data)
            except Exception: actor_data = []
        if isinstance(actor_data, list):
            for actor in actor_data:
                if isinstance(actor, dict) and actor.get('id') and actor.get('name'):
                    aid = str(actor['id'])
                    if aid not in actor_stats:
                        actor_stats[aid] = {'name': actor['name'], 'count': 0, 'id': aid}
                    actor_stats[aid]['count'] += 1

    # 3. 💡 내 찜 리스트 데이터 가공 (ID 매핑 버그 수정)
    for w in watchlists:
        obj = w.tvseries if content_type == 'tv' else w.movie
        if not obj: continue
        
        w.movie_obj = obj
        w.movie_obj.is_watchlisted = True
        
        score, review = user_ratings_map.get(obj.id, (0, ''))
        w.my_score = score
        w.movie_obj.my_score = score
        w.movie_obj.my_review = review
        
        if not hasattr(obj, 'tmdb_title'): 
            obj.tmdb_title = getattr(obj, 'name', '') or getattr(obj, 'tmdb_name', '') or getattr(obj, 'title', '제목 없음')

        obj.display_genre = get_display_genre(getattr(obj, 'tmdb_genre', ''), getattr(obj, 'imdb_genre', ''))
        obj.display_date = get_display_date(getattr(obj, 'tmdb_release_date', None), getattr(obj, 'imdb_release_date', ''))
        obj.display_runtime = get_display_runtime(getattr(obj, 'tmdb_runtime', 0), getattr(obj, 'imdb_runtime', 0))

        g_val = getattr(obj, 'display_genre', '') or ''
        obj.short_genre = g_val.split(',')[0].strip() + '+' if ',' in g_val else (g_val.split('/')[0].strip() + '+' if '/' in g_val else g_val)
        c_val = str(getattr(obj, 'tmdb_production_country_kr', '') or '')
        obj.short_country = c_val.split(',')[0].strip() + '+' if ',' in c_val else c_val

    # 수집한 취향 데이터 정렬
    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_directors = sorted(director_stats.values(), key=lambda x: x['count'], reverse=True)[:5]
    top_actors = sorted(actor_stats.values(), key=lambda x: x['count'], reverse=True)[:5]
    
    hours, minutes = divmod(total_runtime, 60)
    avg_score = round(sum(r.score for r in ratings_list) / len(ratings_list), 1) if ratings_list else 0.0

    # 4. 상단 탭에 뿌려줄 총량 계산
    movie_rated_count = Rating.objects.filter(user=user, score__gt=0, movie__isnull=False).count()
    movie_watchlist_count = Watchlist.objects.filter(user=user, movie__isnull=False).count()
    tv_rated_count = Rating.objects.filter(user=user, score__gt=0, tvseries__isnull=False).count()
    tv_watchlist_count = Watchlist.objects.filter(user=user, tvseries__isnull=False).count()

    context = {
        'my_ratings': ratings_list, 'watchlists': watchlists, 'current_type': content_type, 'active_tab': active_tab,
        'total_rated_count': tv_rated_count if content_type == 'tv' else movie_rated_count,
        'total_watchlist_count': tv_watchlist_count if content_type == 'tv' else movie_watchlist_count,
        'movie_rated_count': movie_rated_count, 'movie_watchlist_count': movie_watchlist_count,
        'tv_rated_count': tv_rated_count, 'tv_watchlist_count': tv_watchlist_count,
        'sort_by': request.GET.get('sort', ''), 'search_query': request.GET.get('search', ''),
        'selected_genres': request.GET.getlist('genres'), 'selected_otts': request.GET.getlist('otts'),
        'selected_ratings': request.GET.getlist('ratings'), 'selected_countries': request.GET.getlist('countries'),
        'exclude_doc': request.GET.get('exclude_doc') == 'on', 'exclude_no_rating': request.GET.get('exclude_no_rating') == 'on',
        'exclude_low_votes': request.GET.get('exclude_low_votes') == 'on',
        
        'total_count': len(ratings_list), 
        'total_hours': hours,
        'total_minutes': minutes,
        'average_score': avg_score,
        'top_genres': top_genres,
        'top_keywords': top_keywords, 
        'top_directors': top_directors,
        'top_actors': top_actors,
        'score_distribution_json': json.dumps(score_distribution), 
    }

    return render(request, 'movie/my_page.html', context)


# 💡 [초보자 안내] 사용자가 찜 버튼을 눌렀을 때 비동기 통신을 담당하는 뷰입니다.
@login_required
@require_POST
def toggle_watchlist(request, movie_id):
    try:
        content_type = request.GET.get('type', 'movie').lower()
        # 🚀 스마트 안전망: 타입이 TV거나 Movie에 없으면 TvSeries 찜으로 처리
        if content_type == 'tv' or not Movie.objects.filter(id=movie_id).exists():
            if TvSeries.objects.filter(id=movie_id).exists():
                series = get_object_or_404(TvSeries, id=movie_id)
                watchlist_item, created = Watchlist.objects.get_or_create(user=request.user, tvseries=series)
                if not created:
                    watchlist_item.delete()
                    is_watchlisted = False
                else: is_watchlisted = True
                return JsonResponse({'status': 'success', 'is_watchlisted': is_watchlisted})

        movie = get_object_or_404(Movie, id=movie_id)
        watchlist_item, created = Watchlist.objects.get_or_create(user=request.user, movie=movie)
        if not created:
            watchlist_item.delete()
            is_watchlisted = False
        else: is_watchlisted = True
        return JsonResponse({'status': 'success', 'is_watchlisted': is_watchlisted})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ==========================================
# 💡 1. 악성 리뷰, 요약 영상 철저히 필터링 (필수 유지)
# ==========================================
EXCLUDE_KEYWORDS = [
    "리뷰", "결말", "해석", "요약", "반응", "리액션", 
    "비하인드", "패러디", "스포", "결말포함", "리뷰어", 
    "몰아보기", "총정리", "reaction", "review", "ending"
]

# ==========================================
# 💡 2. URL 안전 변환기 (오리지널 정석 도메인 복구!)
# ==========================================
def get_safe_embed_url(url):
    """어떤 형태의 유튜브 주소가 들어와도 안전한 오리지널 iframe용 embed 주소로 바꿉니다."""
    if not url: return None
    
    # 11자리 고유 ID만 악착같이 뽑아냅니다.
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', url)
    if match:
        # 💡 [원상 복구] 꼼수(nocookie)를 버리고 가장 안정적인 정식 embed 주소를 사용합니다!
        return f"https://www.youtube.com/embed/{match.group(1)}"
    return url

# ==========================================
# 💡 3. 도메인 제한 없는 '진짜 재생 가능한' 예고편 추출
# ==========================================
def find_playable_trailer(search_items):
    """
    깐깐한 공식 채널(오류 153 원인)을 억지로 찾지 않습니다. 
    자연 검색 최상위에 노출되는 '퍼가기 완벽 허용' 영상 중 악성 리뷰만 걸러냅니다.
    """
    for item in search_items:
        video_id = item.get("id", {}).get("videoId")
        if not video_id: continue
        
        title = item.get("snippet", {}).get("title", "").lower()
        
        # 제목에 리뷰, 결말 등의 단어가 있으면 무조건 패스
        if any(keyword in title for keyword in EXCLUDE_KEYWORDS):
            continue
            
        # 조건을 통과한 첫 번째(가장 관련도 높고 재생 잘 되는) 영상 즉시 반환!
        return video_id
    return None

# ==========================================
# 💡 4. 최종 완성된 지연 로딩(Lazy Load) API 뷰
# ==========================================
def api_lazy_trailer(request):
    target_id = request.GET.get('id')
    media_type = request.GET.get('type')
    
    if not target_id or not media_type:
        return JsonResponse({'status': 'error', 'message': '파라미터 누락'})
        
    model = Movie if media_type == 'movie' else TvSeries
    
    try:
        obj = model.objects.get(id=target_id)
        
        if getattr(obj, 'youtube_trailer_url', None):
            safe_embed_url = get_safe_embed_url(obj.youtube_trailer_url)
            return JsonResponse({'status': 'success', 'trailer_url': safe_embed_url})

        tmdb_url = getattr(obj, 'tmdb_trailer_url', None)
        if tmdb_url:
            oembed_url = f"https://www.youtube.com/oembed?url={tmdb_url}&format=json"
            try:
                ping_res = requests.get(oembed_url, timeout=3)
                if ping_res.status_code == 200:
                    obj.youtube_trailer_url = tmdb_url
                    obj.save(update_fields=['youtube_trailer_url', 'updated_at'])
                    return JsonResponse({'status': 'success', 'trailer_url': get_safe_embed_url(tmdb_url)})
            except Exception:
                pass
            
        YT_API_KEY = os.getenv("YOUTUBE_API_KEY")
        if not YT_API_KEY:
            return JsonResponse({'status': 'error', 'message': 'API Key 미설정'})
            
        media_keyword = "영화" if media_type == 'movie' else "드라마"
        
        queries = []
        if obj.tmdb_title:
            clean_title = obj.tmdb_title.replace("-", " ")
            queries.append(f"{clean_title} {media_keyword} 예고편")
        if obj.tmdb_original_title and obj.tmdb_original_title != obj.tmdb_title:
            clean_original_title = obj.tmdb_original_title.replace("-", " ")
            queries.append(f"{clean_original_title} trailer")
            
        video_url = None
        for q in queries:
            if not q.strip(): continue
            
            # 💡 [플랜 A] 깐깐한 조건: 외부 재생 완벽 보장 (videoSyndicated=true)
            search_url_strict = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={requests.utils.quote(q)}&type=video&maxResults=5&videoEmbeddable=true&videoSyndicated=true&key={YT_API_KEY}"
            res = requests.get(search_url_strict, timeout=5)
            
            # 🚨 할당량 초과 등 API 자체 에러 캐치
            if res.status_code != 200:
                print(f"❌ 유튜브 API 에러 발생 ({res.status_code}): {res.text}")
                # 403 에러면 오늘 치 한도를 다 쓴 것이므로 검색 중단
                if res.status_code == 403: 
                    break 
            
            if res.status_code == 200:
                items = res.json().get('items', [])
                best_video_id = find_playable_trailer(items)
                if best_video_id:
                    video_url = f"https://www.youtube.com/watch?v={best_video_id}"
                    break
            
            # 💡 [플랜 B] 깐깐한 조건에서 못 찾았다면? -> 조건을 살짝 풀어서 재검색! (videoSyndicated 제거)
            if not video_url:
                print(f"⚠️ [{q}] 깐깐한 조건 실패! 조건을 완화하여 재검색합니다.")
                search_url_loose = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={requests.utils.quote(q)}&type=video&maxResults=5&videoEmbeddable=true&key={YT_API_KEY}"
                res_loose = requests.get(search_url_loose, timeout=5)
                
                if res_loose.status_code == 200:
                    items = res_loose.json().get('items', [])
                    best_video_id = find_playable_trailer(items)
                    if best_video_id:
                        video_url = f"https://www.youtube.com/watch?v={best_video_id}"
                        break
                    
        if video_url:
            # 1. 흙 묻은 주소를 노쿠키로 세탁합니다.
            embed_url = get_safe_embed_url(video_url) 
            
            # 2. 💡 [핵심 수정] DB에도 완벽하게 세탁된 노쿠키 주소(embed_url)를 저장합니다!
            obj.youtube_trailer_url = embed_url 
            obj.save(update_fields=['youtube_trailer_url', 'updated_at'])
            
            return JsonResponse({'status': 'success', 'trailer_url': embed_url})
        else:
            return JsonResponse({'status': 'not_found'})
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})




# 💡 [초보자 안내] 유튜브 API 연동 함수
def parse_youtube_duration(duration_str):
    # 유튜브 재생 시간(PT1H2M30S)을 초 단위로 변환해줍니다.
    hours = re.search(r'(\d+)H', duration_str)
    minutes = re.search(r'(\d+)M', duration_str)
    seconds = re.search(r'(\d+)S', duration_str)
    h = int(hours.group(1)) if hours else 0
    m = int(minutes.group(1)) if minutes else 0
    s = int(seconds.group(1)) if seconds else 0
    return h * 3600 + m * 60 + s

def api_youtube_reviews(request, movie_id):
    # 💡 1. URL에 숨겨둔 type 값을 가져옵니다. (안 넘겨주면 기본값 'movie' 적용)
    media_type = request.GET.get('type', 'movie') 

    is_tv = (media_type == 'tv')
    content_type = media_type
    original_title = ''

    # 💡 2. 타입에 따라 검사할 DB를 칼같이 나눕니다!
    if media_type == 'movie':
        try:
            content = Movie.objects.get(id=movie_id)
            title = getattr(content, 'tmdb_title', '') or getattr(content, 'title', '')
            original_title = getattr(content, 'tmdb_original_title', '')
        except Movie.DoesNotExist:
            return JsonResponse({'short': [], 'long': []}, status=404)
            
    elif media_type == 'tv':
        try:
            content = TvSeries.objects.get(id=movie_id)
            title = getattr(content, 'tmdb_title', '') or getattr(content, 'name', '')
            original_title = getattr(content, 'tmdb_original_title', '')
        except TvSeries.DoesNotExist:
            return JsonResponse({'short': [], 'long': []}, status=404)
            
    else:
        # 이상한 타입이 들어오면 차단
        return JsonResponse({'short': [], 'long': []}, status=400)

    # 💡 7일 캐싱 방어막 (기존 v2 캐시를 무시하고 즉시 새 로직을 적용하기 위해 v3로 올림!)
    cache_key = f'yt_reviews_{content_type}_{movie_id}_v3'
    cached_data = cache.get(cache_key)
    if cached_data: return JsonResponse(cached_data)
    
    api_key = getattr(settings, 'YOUTUBE_API_KEY', '')
    if not api_key: return JsonResponse({'short': [], 'long': []})

    # =========================================================
    # 🚀 [업그레이드된 무적의 검색어 조합 로직]
    # =========================================================
    genre_str = getattr(content, 'tmdb_genre', '')
    actors_str = getattr(content, 'tmdb_actors', '')
    director_str = getattr(content, 'tmdb_director', '')

    # 💡 애니메이션, 다큐멘터리가 아닐 때만 1번 인물 키워드 추출 (성우/무명 필터링 방지)
    main_person = ""
    if "애니메이션" not in genre_str and "다큐멘터리" not in genre_str:
        if actors_str:
            main_person = actors_str.split(',')[0].strip()
        elif director_str:
            main_person = director_str.split(',')[0].strip()

    has_korean = any(ord(c) >= 0xAC00 and ord(c) <= 0xD7A3 for c in title)
    
    # 기본 제목은 따옴표로 강제 매칭
    search_title = f'"{title}"'
    
    # 원제가 다르면 묶어서 추가 (예: "히트맨" "HITMAN")
    if original_title and original_title.lower() != title.lower(): 
        search_title += f' "{original_title}"'

    # 주연 배우/감독 추가 (따옴표 없이 얹어서 유튜브의 찰떡같은 유연한 검색 허용)
    if main_person:
        search_title += f' {main_person}'

    # 최종 검색어 완성
    if is_tv: 
        query = f'{search_title} (리뷰 | 요약 | 결말포함 | 정주행 | 몰아보기 | 복습 | 예습)' if has_korean else f'{search_title} (review | recap | ending | full story | binge)'
    else: 
        query = f'{search_title} (리뷰 | 요약 | 결말포함 | 정주행 | 몰아보기 | 복습 | 예습)' if has_korean else f'{search_title} (review | recap | ending | full story)'

    try:
        # 유튜브 API 검색 요청
        search_url = f'https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&key={api_key}&maxResults=9'
        search_res = requests.get(search_url, timeout=4.0).json()
        video_ids = [item['id']['videoId'] for item in search_res.get('items', []) if 'id' in item and 'videoId' in item['id']]
        
        if not video_ids: 
            return JsonResponse({'short': [], 'long': []})

        # 영상 상세 정보 요청
        ids_str = ','.join(video_ids)
        details_url = f'https://www.googleapis.com/youtube/v3/videos?part=contentDetails,snippet&id={ids_str}&key={api_key}'
        details_res = requests.get(details_url, timeout=4.0).json()

        short_vids, long_vids = [], []
        for item in details_res.get('items', []):
            duration = parse_youtube_duration(item['contentDetails']['duration'])
            video_data = {'id': item['id'], 'title': item['snippet']['title'], 'thumbnail': item['snippet']['thumbnails']['medium']['url'], 'duration': duration}
            if duration <= 600: short_vids.append(video_data)
            else: long_vids.append(video_data)

        result_data = {'short': short_vids, 'long': long_vids}
        if short_vids or long_vids: 
            cache.set(cache_key, result_data, timeout=60 * 60 * 24 * 7)
            
        return JsonResponse(result_data)

    except Exception as e:
        print(f'🚨 유튜브 API 통신 에러: {e}')
        return JsonResponse({'short': [], 'long': []})


def search_results(request):
    query = request.GET.get('q', '').strip()
    
    # 💡 검색어가 없으면 빈 결과 반환
    if not query:
        return render(request, 'search_results.html', {'query': query, 'people': [], 'movies': [], 'tv_series': []})
    
    # =========================================================
    # 🚀 1. 검색어 전처리 (원본 + 치환어 동시 타격 정규식)
    # =========================================================
    q_clean_orig = query.replace(' ', '').lower()
    regex_orig = r'\s*'.join(re.escape(char) for char in q_clean_orig)
    synonyms = {
        # 🦸‍♂️ 프랜차이즈 / 영화 제목 오타 방어
        '어벤져스': '어벤저스',
        '베트맨': '배트맨',
        '수퍼맨': '슈퍼맨',
        '에일리언': '에이리언',
        '주라기': '쥬라기',
        '케리비안': '캐리비안',
        '인디애나': '인디아나',
        '메트릭스': '매트릭스',
        '터미네타': '터미네이터',
        '스타트랙': '스타트렉',

        # 👤 해외 배우/감독 이름 방어 (띄어쓰기, 붙여쓰기 모두 대비)
        '탐 크루즈': '톰 크루즈', '탐크루즈': '톰크루즈',
        '탐 하디': '톰 하디', '탐하디': '톰하디',
        '탐 홀랜드': '톰 홀랜드', '탐홀랜드': '톰홀랜드',
        '탐 행크스': '톰 행크스', '탐행크스': '톰행크스',
        '브레드 피트': '브래드 피트', '브레드피트': '브래드피트',
        '죠니 뎁': '조니 뎁', '죠니뎁': '조니뎁',
        '엔젤리나 졸리': '안젤리나 졸리', '엔젤리나졸리': '안젤리나졸리',
        
        # (이름의 일부만 쓰여도 안전한 고유명사들)
        '레오날도': '레오나르도',  # 레오날도 디카프리오
        '조한슨': '요한슨',      # 스칼렛 조한슨 -> 스칼렛 요한슨
        '슈왈츠제네거': '슈워제네거', '슈왈제네거': '슈워제네거',
        '카메룬': '카메론',      # 제임스 카메룬 -> 카메론 (아바타 감독)
        '놀런': '놀란',        # 크리스토퍼 놀런 -> 크리스토퍼 놀란
        '질렌홀': '질렌할',      # 제이크 질렌홀 -> 질렌할
        '펠트로': '팰트로',      # 기네스 펠트로 -> 팰트로

        # 🚀 [핵심 추가] 팝업과 동일하게 영어 검색어 치환
        'cruise': '크루즈', 'tom': '톰', 'brad': '브래드', 'pitt': '피트', 
        'spider': '스파이더', 'man': '맨', 'batman': '배트맨', 'superman': '슈퍼맨',
        'iron': '아이언'
    }
    
    processed_query = query.lower()
    for key, val in synonyms.items():
        processed_query = processed_query.replace(key, val)
    
    q_clean_syn = processed_query.replace(' ', '')
    regex_syn = r'\s*'.join(re.escape(char) for char in q_clean_syn)

    # 💡 원본과 다르면 OR(|)로 합치기
    if regex_orig != regex_syn:
        regex_str = f"({regex_orig}|{regex_syn})"
        search_keywords = [q_clean_orig, q_clean_syn]
    else:
        regex_str = regex_orig
        search_keywords = [q_clean_orig]

    # =========================================================
    # 🚀 2. 작품 검색 (DB 스캔)
    # =========================================================
    m_cond = Q(tmdb_title__iregex=regex_str)
    if hasattr(Movie, 'translated_title'): m_cond |= Q(translated_title__iregex=regex_str)
    if hasattr(Movie, 'tmdb_original_title'): m_cond |= Q(tmdb_original_title__iregex=regex_str)
    if hasattr(Movie, 'tmdb_actors'): m_cond |= Q(tmdb_actors__iregex=regex_str)
    if hasattr(Movie, 'tmdb_actor_details'): m_cond |= Q(tmdb_actor_details__iregex=regex_str)
    if hasattr(Movie, 'tmdb_director'): m_cond |= Q(tmdb_director__iregex=regex_str)

    t_cond = Q(tmdb_title__iregex=regex_str)
    if hasattr(TvSeries, 'translated_title'): t_cond |= Q(translated_title__iregex=regex_str)
    if hasattr(TvSeries, 'tmdb_original_title'): t_cond |= Q(tmdb_original_title__iregex=regex_str)
    if hasattr(TvSeries, 'tmdb_actors'): t_cond |= Q(tmdb_actors__iregex=regex_str)
    if hasattr(TvSeries, 'tmdb_actor_details'): t_cond |= Q(tmdb_actor_details__iregex=regex_str)
    if hasattr(TvSeries, 'tmdb_director'): t_cond |= Q(tmdb_director__iregex=regex_str)
    
    movies = Movie.objects.filter(m_cond).order_by('-imdb_vote_count', '-id')
    tv_series = TvSeries.objects.filter(t_cond).order_by('-imdb_vote_count', '-id')
    
    # =========================================================
    # 🚀 3. 인물 추출 (JSON 스캔)
    # =========================================================
    matched_people = {}

    def extract_people_from_queryset(queryset):
        for item in queryset[:50]:
            item_votes = getattr(item, 'imdb_vote_count', 0) or 0
            
            actors = getattr(item, 'tmdb_actor_details', [])
            if isinstance(actors, str):
                try: actors = json.loads(actors)
                except Exception: actors = []
            
            if isinstance(actors, list):
                for actor in actors:
                    actor_name = str(actor.get('name', '')).replace(' ', '').lower()
                    actor_original = str(actor.get('original_name', '')).replace(' ', '').lower()
                    
                    if any(kw in actor_name or (kw and kw in actor_original) for kw in search_keywords):
                        person_id = actor.get('id')
                        if person_id:
                            if person_id not in matched_people:
                                matched_people[person_id] = {'id': person_id, 'name': actor.get('name'), 'profile_url': actor.get('profile_url', ''), 'type': '배우', 'score': 0}
                            matched_people[person_id]['score'] += item_votes
            
            director_name = str(getattr(item, 'tmdb_director', '') or '')
            dir_clean = director_name.replace(' ', '').lower()
            if any(kw in dir_clean for kw in search_keywords):
                dir_id = getattr(item, 'tmdb_director_id', None)
                if dir_id:
                    if dir_id not in matched_people:
                        matched_people[dir_id] = {'id': dir_id, 'name': director_name, 'profile_url': getattr(item, 'tmdb_director_image_url', ''), 'type': '감독', 'score': 0}
                    matched_people[dir_id]['score'] += item_votes
            
            writer_name = str(getattr(item, 'tmdb_screenwriter', '') or '')
            wrt_clean = writer_name.replace(' ', '').lower()
            if any(kw in wrt_clean for kw in search_keywords):
                wrt_id = getattr(item, 'tmdb_screenwriter_id', None)
                if wrt_id:
                    if wrt_id not in matched_people:
                        matched_people[wrt_id] = {'id': wrt_id, 'name': writer_name, 'profile_url': '', 'type': '각본가', 'score': 0}
                    matched_people[wrt_id]['score'] += item_votes

    extract_people_from_queryset(movies)
    extract_people_from_queryset(tv_series)

    sorted_people = sorted(matched_people.values(), key=lambda x: x['score'], reverse=True)

    context = {
        'query': query,
        'movies': movies,
        'tv_series': tv_series,
        'people': sorted_people[:15] 
    }
    
    return render(request, 'search_results.html', context)



def my_taste_analysis(request):
    # 1. 로그인한 유저의 모든 평점 기록 가져오기 (성능을 위해 select_related 사용)
    ratings = Rating.objects.filter(user=request.user).select_related('movie', 'tvseries')
    
    # 분석을 담을 빈 바구니들 준비
    total_runtime = 0
    genre_counts = defaultdict(int)
    director_counts = defaultdict(int)
    actor_counts = defaultdict(int)
    
    # 차트용 별점 분포 (0.5 ~ 5.0)
    score_distribution = {str(i*0.5): 0 for i in range(1, 11)} 
    
    for r in ratings:
        # 별점 분포 카운트
        score_distribution[str(r.score)] += 1
        
        # 영화인지 시리즈인지 타겟 작품 추출
        obj = r.movie if r.movie else r.tvseries
        if not obj:
            continue
            
        # 2. 누적 상영시간 합산
        total_runtime += (obj.tmdb_runtime or 0)
        
        # 3. 장르 카운트 (쉼표로 구분된 문자열을 쪼개서 각각 1씩 추가)
        if obj.tmdb_genre:
            for g in obj.tmdb_genre.split(','):
                genre_counts[g.strip()] += 1
                
        # 4. 감독 카운트
        if obj.tmdb_director:
            director_counts[obj.tmdb_director] += 1
            
        # 5. 배우 카운트 (JSON 필드에서 이름만 쏙쏙 뽑아냄)
        if obj.tmdb_actor_details:
            for actor in obj.tmdb_actor_details:
                actor_counts[actor.get('name', '')] += 1

    # 6. 통계 결과 정렬 (가장 많이 나온 순서대로 정렬 후 TOP 3~5만 자르기)
    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_directors = sorted(director_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    top_actors = sorted(actor_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # 시간을 보기 좋게 변환
    hours, minutes = divmod(total_runtime, 60)
    
    context = {
        'total_hours': hours,
        'total_minutes': minutes,
        'total_count': ratings.count(),
        'average_score': round(ratings.aggregate(Avg('score'))['score__avg'] or 0, 1),
        'top_genres': top_genres,
        'top_directors': top_directors,
        'top_actors': top_actors,
        # 차트를 그리기 위해 JSON 문자열로 변환하여 넘김
        'score_distribution_json': json.dumps(score_distribution), 
    }
    return render(request, 'my_taste.html', context)


# =====================================================================
# 💡 상세페이지: 키워드 연관작 AJAX 로딩 뷰 (영화 + 시리즈 동시 제공)
# =====================================================================
def api_keyword_recommend(request):
    keyword = request.GET.get('keyword', '').strip()
    item_type = request.GET.get('type', 'movie')
    exclude_id = request.GET.get('exclude_id', 0)

    if not keyword:
        return JsonResponse({'status': 'error', 'message': '키워드가 없습니다.'})

    try: exclude_id = int(exclude_id)
    except ValueError: exclude_id = 0

    # 현재 페이지 타입에 맞춰 자기 자신만 제외 (영화/시리즈 ID 충돌 방지)
    movie_exclude = exclude_id if item_type == 'movie' else 0
    tv_exclude = exclude_id if item_type == 'tv' else 0

    # 🚀 영화와 시리즈 각각 IMDb 평가순 상위 10개씩 추출
    movie_qs = Movie.objects.filter(tmdb_keywords__icontains=keyword).exclude(id=movie_exclude).order_by('-imdb_vote_count')[:10]
    tv_qs = TvSeries.objects.filter(tmdb_keywords__icontains=keyword).exclude(id=tv_exclude).order_by('-imdb_vote_count')[:10]

    # 영화 Context
    movie_context = {
        'recommended_movies': movie_qs,
        'is_tv': False,
        'is_fallback': False,
        'is_anonymous': request.user.is_anonymous,
        'current_type': 'movie',
        'is_keyword_rec': True,
        'keyword': keyword,
    }
    # 시리즈 Context
    tv_context = {
        'recommended_movies': tv_qs,
        'is_tv': True,
        'is_fallback': False,
        'is_anonymous': request.user.is_anonymous,
        'current_type': 'tv',
        'is_keyword_rec': True,
        'keyword': keyword,
    }

    # 각각 템플릿 렌더링
    movie_html = render_to_string('partials/comp_recommend_row.html', movie_context, request=request)
    tv_html = render_to_string('partials/comp_recommend_row.html', tv_context, request=request)

    return JsonResponse({
        'status': 'success',
        'movie_html': movie_html,
        'tv_html': tv_html,
        'movie_count': len(movie_qs),
        'tv_count': len(tv_qs),
    })



def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for: return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

@require_POST
def api_report_trailer(request):
    target_id = request.POST.get('id')
    media_type = request.POST.get('type')
    
    if not target_id or not media_type:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청입니다.'})

    # 비로그인 유저도 구별할 수 있도록 세션 강제 부여
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    ip_address = get_client_ip(request)
    user = request.user if request.user.is_authenticated else None

    # 💡 [캐시 방어막] 동일 IP나 세션에서 30초 내에 연타 클릭 시 강제 차단!
    cache_key = f"trailer_report_{ip_address}_{target_id}_{media_type}"
    if cache.get(cache_key):
        return JsonResponse({'status': 'error', 'message': '잠시 후 다시 시도해주세요.'})
    cache.set(cache_key, True, timeout=30) 

    try:
        # 중복 검사 로직 (미해결된 동일 유저/세션의 내역이 있는지 스캔)
        query = Q(is_resolved=False)
        if user: query &= Q(user=user)
        else: query &= Q(session_key=session_key)

        if media_type == 'movie':
            obj = Movie.objects.get(id=target_id)
            query &= Q(movie=obj)
            if TrailerReport.objects.filter(query).exists():
                return JsonResponse({'status': 'already', 'message': '이미 신고하셨습니다.'})
                
            TrailerReport.objects.create(movie=obj, user=user, session_key=session_key, ip_address=ip_address)
            active_count = TrailerReport.objects.filter(movie=obj, is_resolved=False).count()
        else:
            obj = TvSeries.objects.get(id=target_id)
            query &= Q(tvseries=obj)
            if TrailerReport.objects.filter(query).exists():
                return JsonResponse({'status': 'already', 'message': '이미 신고하셨습니다.'})
                
            TrailerReport.objects.create(tvseries=obj, user=user, session_key=session_key, ip_address=ip_address)
            active_count = TrailerReport.objects.filter(tvseries=obj, is_resolved=False).count()

        return JsonResponse({'status': 'success', 'count': active_count})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
