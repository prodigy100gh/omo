import re
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator

class Movie(models.Model):
    # ==========================================
    # 1. 식별자 및 번역 필드
    # ==========================================
    tmdb_id = models.IntegerField(unique=True, null=True, blank=True, verbose_name="TMDB ID")
    tmdb_imdb_id = models.CharField(max_length=20, unique=True, blank=True, null=True, verbose_name="IMDb ID")
    
    tmdb_title = models.CharField(max_length=255, verbose_name="TMDB 영화 제목")
    tmdb_original_title = models.CharField(max_length=255, blank=True, default="", verbose_name="TMDB 원제")
    translated_title = models.CharField(max_length=255, blank=True, default="", verbose_name="AI 번역 제목")

    # ==========================================
    # 2. TMDB 출처 기본 데이터
    # ==========================================
    tmdb_genre = models.CharField(max_length=255, blank=True, default="", verbose_name="TMDB 장르")
    
    tmdb_release_date = models.DateField(null=True, blank=True, verbose_name="TMDB 개봉일")
    tmdb_release_date_kr = models.DateField(null=True, blank=True, verbose_name="TMDB K개봉일")
    tmdb_runtime = models.IntegerField(default=0, verbose_name="TMDB 상영시간(분)")
    
    tmdb_rating = models.FloatField(default=0.0, verbose_name="TMDB 평점")
    tmdb_vote_count = models.IntegerField(default=0, verbose_name="TMDB 평가수")
    
    tmdb_overview = models.TextField(blank=True, default="", verbose_name="TMDB 줄거리")
    tmdb_poster_url = models.URLField(max_length=500, blank=True, default="", verbose_name="TMDB 포스터 URL")
    backdrop_path = models.CharField(max_length=200, null=True, blank=True, verbose_name="TMDB 가로 배경 URL")
    tmdb_trailer_url = models.URLField(max_length=500, blank=True, default="", verbose_name="TMDB 공식 예고편 URL")

    is_adult_content = models.BooleanField(default=False)
    
    # ==========================================
    # 3. TMDB 인물 및 상세 부가 데이터
    # ==========================================
    tmdb_director = models.CharField(max_length=255, blank=True, default="", verbose_name="TMDB 감독")
    tmdb_director_id = models.IntegerField(null=True, blank=True, verbose_name="TMDB 감독 고유 ID")
    tmdb_director_image_url = models.URLField(max_length=500, blank=True, default="", verbose_name="TMDB 감독 사진 URL")
    tmdb_screenwriter = models.CharField(max_length=255, blank=True, default="", verbose_name="TMDB 각본가")
    tmdb_screenwriter_id = models.IntegerField(null=True, blank=True, verbose_name="TMDB 각본가 고유 ID")
    
    tmdb_actors = models.TextField(blank=True, default="", verbose_name="TMDB 상위 출연진 (단순 문자열)")
    tmdb_actor_details = models.JSONField(default=list, blank=True, verbose_name="TMDB 출연진 상세 (JSON)")
    
    tmdb_streaming_providers = models.JSONField(default=list, blank=True, verbose_name="TMDB OTT 정보(JSON)")
    tmdb_recommended_movies = models.JSONField(default=list, blank=True, verbose_name="TMDB 추천/유사 영화 (JSON)")
    tmdb_keywords = models.TextField(blank=True, default="", verbose_name="TMDB 연관 키워드")
    
    # ==========================================
    # 4. TMDB 등급, 제작, 국가 데이터
    # ==========================================
    tmdb_certification_kr = models.CharField(max_length=50, blank=True, default="", verbose_name="TMDB KR등급")
    tmdb_certification_us = models.CharField(max_length=50, blank=True, default="", verbose_name="TMDB US등급")

    tmdb_original_language = models.CharField(max_length=50, null=True, blank=True, verbose_name="원어")
    
    tmdb_budget = models.BigIntegerField(default=0, verbose_name="TMDB 제작 예산 ($)")
    tmdb_revenue = models.BigIntegerField(default=0, verbose_name="TMDB 흥행 수익 ($)")

    tmdb_production_country_code = models.CharField(max_length=50, blank=True, default="", verbose_name="TMDB 국가 코드 (ISO)")
    tmdb_production_country_eng = models.CharField(max_length=200, blank=True, default="", verbose_name="TMDB 영문 국가명")
    tmdb_production_country_kr = models.CharField(max_length=200, blank=True, default="", verbose_name="TMDB 한글 국가명")

    # ==========================================
    # 5. IMDb 출처 및 시스템 관리 필드
    # ==========================================
    imdb_rating = models.FloatField(null=True, blank=True, default=0.0, verbose_name="IMDb 평점")
    imdb_vote_count = models.IntegerField(null=True, blank=True, default=0, verbose_name="IMDb 평가수")
    imdb_runtime = models.IntegerField(null=True, blank=True, default=0, verbose_name="IMDb 상영시간(분)")
    imdb_genre = models.CharField(max_length=255, blank=True, default="", verbose_name="IMDb 장르")
    imdb_release_date = models.CharField(max_length=20, blank=True, default="", verbose_name="IMDb 개봉 연도")

    youtube_trailer_url = models.CharField(max_length=500, blank=True, null=True, verbose_name="유튜브 자체 검색 예고편 URL")

    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="DB 최초 저장일")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="DB 최종 수정일")

    # 💡 이 아래에 save 메서드를 덮어쓰는 코드를 추가합니다.
    def save(self, *args, **kwargs):
        # URL이 존재하고, 아직 embed 형태가 아닐 때만 작동
        if self.youtube_trailer_url and "embed/" not in self.youtube_trailer_url:
            print(f"🔄 [Movie] URL 변환 시도: {self.youtube_trailer_url}")
            
            # 💡 유튜브 11자리 비디오 ID만 귀신같이 찾아내는 정규식
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', self.youtube_trailer_url)
            
            if match:
                video_id = match.group(1)
                self.youtube_trailer_url = f"https://www.youtube.com/embed/{video_id}"
                print(f"✅ [Movie] 변환 성공: {self.youtube_trailer_url}")
            else:
                print("❌ [Movie] 변환 실패: 11자리 ID를 찾을 수 없습니다.")
                
        super().save(*args, **kwargs)

    def __str__(self):
        # 날짜 객체에서 .year를 뽑아서 연도만 가져옵니다.
        if self.tmdb_release_date:
            return f"{self.tmdb_title} ({self.tmdb_release_date.year})"
        return f"{self.tmdb_title} (연도미상)"

    @property
    def display_ott_providers(self):
        import json
        raw_providers = self.tmdb_streaming_providers
        if not raw_providers:
            return []

        # 💡 [안전장치] DB에 문자열로 저장되었을 경우를 대비해 JSON 파싱
        if isinstance(raw_providers, str):
            try:
                raw_providers = json.loads(raw_providers.replace("'", '"'))
            except:
                return []

        # 💡 1. 통제소를 함수 안으로 완전히 가져와서 인식 오류 방지
        custom_logos = {
            'Watcha': '/static/images/WATCHA_icon_Square.png',
            'Wavve': '/static/images/Wavve_icon.png',
            'TVING': 'https://www.tving.com/favicon.ico', # 티빙 아이콘도 깔끔하게 추가!
        }
        
        # 💡 2. 대소문자 오류 방지를 위해 키값을 '전부 소문자'로 등록
        sort_order = {
            'netflix': 1,
            'tving': 2,
            'coupang play': 3,
            'wavve': 4,
            'disney+': 5,
            'watcha': 6,
            'apple tv+': 7,
            'amazon prime video': 8,
        }

        clean_list = []
        seen_providers = set()

        for prov in raw_providers:
            if not isinstance(prov, dict): continue
            
            name = prov.get('provider_name', '')
            logo_url = prov.get('logo_url', '') or prov.get('logo_path', '')
            
            name_lower = name.lower()

            # 💡 [추가] 'ads' (광고형 요금제)가 포함된 경우 아예 리스트에서 배제시킴!
            if 'ads' in name_lower:
                continue

            # 3. 이름 통일
            if 'netflix' in name_lower: name = 'Netflix'
            elif 'disney' in name_lower: name = 'Disney+'
            elif 'watcha' in name_lower or '왓챠' in name: name = 'Watcha'
            elif 'wavve' in name_lower or '웨이브' in name: name = 'Wavve'

            # 4. 중복 제거
            if name in seen_providers:
                continue

            # 5. 로고 갈아끼우기
            if name in custom_logos:
                logo_url = custom_logos[name]
            elif logo_url and logo_url.startswith('/'):
                # 커스텀 로고가 없는 디즈니, 애플, 쿠팡 등은 TMDB 오리지널 이미지 경로를 달아줌
                logo_url = f"https://image.tmdb.org/t/p/original{logo_url}"

            clean_list.append({
                'provider_name': name,
                'logo_url': logo_url
            })
            seen_providers.add(name)

        # 💡 6. 최종 정렬: provider_name을 소문자로 바꿔서 sort_order 번호를 찾아 정렬 (없으면 99등)
        clean_list.sort(key=lambda x: sort_order.get(x['provider_name'].lower(), 99))

        return clean_list
    @property
    def display_year(self):
        # 일반 영화는 무조건 개봉일 연도만 표기
        if self.tmdb_release_date:
            return str(self.tmdb_release_date)[:4]
        return "----"

    # ---------------------------------------------------------
    # 💡 [카드 전용 장르 속성 추가] 상세 페이지는 건드리지 않습니다!
    # ---------------------------------------------------------
    @property
    def card_display_genre(self):
        """카드 오버레이 툴팁용 (다큐, 애니 축약)"""
        genre_str = self.tmdb_genre or self.imdb_genre or "정보 없음"
        return genre_str.replace("다큐멘터리", "다큐").replace("애니메이션", "애니")

    @property
    def card_short_genre(self):
        """카드 하단 노출용 (다큐, 애니 축약)"""
        genre_str = self.tmdb_genre or self.imdb_genre or ""
        if not genre_str:
            return "장르 없음"
        
        first_genre = genre_str.split(',')[0].strip()
        return first_genre.replace("다큐멘터리", "다큐").replace("애니메이션", "애니")

    @property
    def poster_thumb_url(self):
        """그리드 카드용 저용량(w342→w185) 포스터 URL 동적 생성"""
        if self.tmdb_poster_url:
            return self.tmdb_poster_url.replace('/w500/', '/w185/')
        return ""



# 💡 [추가] 기존 import 수정 없이 파일 맨 밑에 아래 클래스만 그대로 추가하시면 됩니다!
# 💡 [수정] 영화 모델처럼 깔끔하게 구역을 나누고 한글 이름(verbose_name)을 완벽하게 부여한 TvSeries 모델
class TvSeries(models.Model):
    # ==========================================
    # 1. 식별자 및 번역 필드
    # ==========================================
    tmdb_id = models.IntegerField(unique=True, null=True, blank=True, verbose_name="TMDB ID")
    tmdb_imdb_id = models.CharField(max_length=50, null=True, blank=True, db_index=True, verbose_name="IMDb ID")
    
    tmdb_title = models.CharField(max_length=255, verbose_name="TMDB 시리즈 제목")
    tmdb_original_title = models.CharField(max_length=255, null=True, blank=True, verbose_name="TMDB 원제")
    translated_title = models.CharField(max_length=255, null=True, blank=True, verbose_name="AI 번역 제목")

    # ==========================================
    # 2. TMDB 출처 기본 데이터
    # ==========================================
    tmdb_genre = models.CharField(max_length=255, null=True, blank=True, verbose_name="TMDB 장르")
    tmdb_release_date = models.DateField(null=True, blank=True, verbose_name="TMDB 방영 시작일")
    tmdb_runtime = models.IntegerField(default=0, verbose_name="TMDB 에피소드 평균 상영시간(분)")

    tmdb_rating = models.FloatField(default=0.0, verbose_name="TMDB 평점")
    tmdb_vote_count = models.IntegerField(default=0, verbose_name="TMDB 평가수")

    tmdb_overview = models.TextField(null=True, blank=True, verbose_name="TMDB 줄거리")
    tmdb_poster_url = models.URLField(max_length=500, null=True, blank=True, verbose_name="TMDB 포스터 URL")
    backdrop_path = models.CharField(max_length=255, null=True, blank=True, verbose_name="TMDB 가로 배경 URL")
    tmdb_trailer_url = models.URLField(max_length=500, null=True, blank=True, verbose_name="TMDB 공식 예고편 URL")

    # ==========================================
    # 3. TMDB 인물 및 상세 부가 데이터
    # ==========================================
    tmdb_director = models.CharField(max_length=255, null=True, blank=True, verbose_name="TMDB 총괄 프로듀서/감독")
    tmdb_director_id = models.IntegerField(null=True, blank=True, verbose_name="TMDB 감독 고유 ID")
    tmdb_director_image_url = models.URLField(max_length=500, null=True, blank=True, verbose_name="TMDB 감독 사진 URL")
    tmdb_screenwriter = models.CharField(max_length=255, null=True, blank=True, verbose_name="TMDB 각본가")
    tmdb_screenwriter_id = models.IntegerField(null=True, blank=True, verbose_name="TMDB 각본가 고유 ID")

    tmdb_actors = models.CharField(max_length=500, null=True, blank=True, verbose_name="TMDB 상위 출연진 (단순 문자열)")
    tmdb_actor_details = models.JSONField(default=list, null=True, blank=True, verbose_name="TMDB 출연진 상세 (JSON)")
    
    tmdb_streaming_providers = models.JSONField(default=list, null=True, blank=True, verbose_name="TMDB OTT 정보 (JSON)")
    tmdb_recommended_movies = models.JSONField(default=list, null=True, blank=True, verbose_name="TMDB 추천/유사 드라마 (JSON)")
    tmdb_keywords = models.CharField(max_length=500, null=True, blank=True, verbose_name="TMDB 연관 키워드")

    # ==========================================
    # 4. TMDB 등급, 제작, 시즌, 국가 데이터
    # ==========================================
    tmdb_certification_kr = models.CharField(max_length=50, null=True, blank=True, verbose_name="TMDB KR등급")
    tmdb_certification_us = models.CharField(max_length=50, null=True, blank=True, verbose_name="TMDB US등급")

    tmdb_original_language = models.CharField(max_length=50, null=True, blank=True, verbose_name="원어")
    
    tmdb_budget = models.BigIntegerField(default=0, verbose_name="TMDB 제작 예산 ($)")
    tmdb_revenue = models.BigIntegerField(default=0, verbose_name="TMDB 흥행 수익 ($)")

    tmdb_production_country_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="TMDB 국가 코드 (ISO)")
    tmdb_production_country_eng = models.CharField(max_length=100, null=True, blank=True, verbose_name="TMDB 영문 국가명")
    tmdb_production_country_kr = models.CharField(max_length=100, null=True, blank=True, verbose_name="TMDB 한글 국가명")

    tmdb_number_of_seasons = models.IntegerField(null=True, blank=True, default=0, verbose_name="TMDB 총 시즌 수")
    tmdb_status = models.CharField(max_length=50, null=True, blank=True, verbose_name="TMDB 방영 상태 (완결/방영중)")
    seasons_data = models.JSONField(null=True, blank=True, verbose_name="TMDB 시즌별 상세 정보 (JSON)")

    # ==========================================
    # 5. IMDb 출처 및 시스템 관리 필드
    # ==========================================
    imdb_rating = models.FloatField(default=0.0, db_index=True, verbose_name="IMDb 평점")
    imdb_vote_count = models.IntegerField(default=0, db_index=True, verbose_name="IMDb 평가수")
    imdb_runtime = models.IntegerField(default=0, verbose_name="IMDb 평균 상영시간(분)")
    imdb_genre = models.CharField(max_length=255, null=True, blank=True, verbose_name="IMDb 장르")
    imdb_release_date = models.CharField(max_length=50, null=True, blank=True, verbose_name="IMDb 방영 시작 연도")

    youtube_trailer_url = models.CharField(max_length=500, blank=True, null=True, verbose_name="유튜브 자체 검색 예고편 URL")

    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="DB 최초 저장일")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="DB 최종 수정일")

    # 💡 이 아래에 save 메서드를 덮어쓰는 코드를 추가합니다.
    def save(self, *args, **kwargs):
        if self.youtube_trailer_url and "embed/" not in self.youtube_trailer_url:
            print(f"🔄 [TvSeries] URL 변환 시도: {self.youtube_trailer_url}")
            
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', self.youtube_trailer_url)
            
            if match:
                video_id = match.group(1)
                self.youtube_trailer_url = f"https://www.youtube.com/embed/{video_id}"
                print(f"✅ [TvSeries] 변환 성공: {self.youtube_trailer_url}")
            else:
                print("❌ [TvSeries] 변환 실패: 11자리 ID를 찾을 수 없습니다.")
                
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'tv_series' 
        ordering = ['-imdb_vote_count', '-tmdb_release_date']

    def __str__(self):
        # 💡 날짜 객체(.date)인 경우 .year를 사용하고, 안전하게 예외 처리를 추가합니다.
        if self.tmdb_release_date:
            try:
                return f"[{self.id}] {self.tmdb_title} ({self.tmdb_release_date.year})"
            except AttributeError:
                # 혹시 데이터가 문자열로 남아있는 경우를 대비한 방어 코드
                return f"[{self.id}] {self.tmdb_title} ({str(self.tmdb_release_date)[:4]})"
        return f"[{self.id}] {self.tmdb_title} (연도미상)"

    @property
    def display_ott_providers(self):
        import json
        raw_providers = self.tmdb_streaming_providers
        if not raw_providers:
            return []

        # 💡 [안전장치] DB에 문자열로 저장되었을 경우를 대비해 JSON 파싱
        if isinstance(raw_providers, str):
            try:
                raw_providers = json.loads(raw_providers.replace("'", '"'))
            except:
                return []

        # 💡 1. 통제소를 함수 안으로 완전히 가져와서 인식 오류 방지
        custom_logos = {
            'Watcha': '/static/images/WATCHA_icon_Square.png',
            'Wavve': '/static/images/Wavve_icon.png',
            'TVING': 'https://www.tving.com/favicon.ico', # 티빙 아이콘도 깔끔하게 추가!
        }
        
        # 💡 2. 대소문자 오류 방지를 위해 키값을 '전부 소문자'로 등록
        sort_order = {
            'netflix': 1,
            'tving': 2,
            'coupang play': 3,
            'wavve': 4,
            'disney+': 5,
            'watcha': 6,
            'apple tv+': 7,
            'amazon prime video': 8,
        }

        clean_list = []
        seen_providers = set()

        for prov in raw_providers:
            if not isinstance(prov, dict): continue
            
            name = prov.get('provider_name', '')
            logo_url = prov.get('logo_url', '') or prov.get('logo_path', '')
            
            name_lower = name.lower()

            # 💡 [추가] 'ads' (광고형 요금제)가 포함된 경우 아예 리스트에서 배제시킴!
            if 'ads' in name_lower:
                continue

            # 3. 이름 통일
            if 'netflix' in name_lower: name = 'Netflix'
            elif 'disney' in name_lower: name = 'Disney+'
            elif 'watcha' in name_lower or '왓챠' in name: name = 'Watcha'
            elif 'wavve' in name_lower or '웨이브' in name: name = 'Wavve'

            # 4. 중복 제거
            if name in seen_providers:
                continue

            # 5. 로고 갈아끼우기
            if name in custom_logos:
                logo_url = custom_logos[name]
            elif logo_url and logo_url.startswith('/'):
                # 커스텀 로고가 없는 디즈니, 애플, 쿠팡 등은 TMDB 오리지널 이미지 경로를 달아줌
                logo_url = f"https://image.tmdb.org/t/p/original{logo_url}"

            clean_list.append({
                'provider_name': name,
                'logo_url': logo_url
            })
            seen_providers.add(name)

        # 💡 6. 최종 정렬: provider_name을 소문자로 바꿔서 sort_order 번호를 찾아 정렬 (없으면 99등)
        clean_list.sort(key=lambda x: sort_order.get(x['provider_name'].lower(), 99))

        return clean_list

    @property
    def display_year(self):
        # 1. 시즌 데이터가 있고, 2개 이상일 경우 (시즌 1, 시즌 2...)
        if self.seasons_data and len(self.seasons_data) > 1:
            try:
                # 첫 시즌과 마지막 시즌의 연도 4자리 추출 (값이 없으면 빈 문자열)
                first_year_full = str(self.seasons_data[0].get('air_date', '') or '')[:4]
                last_year_full = str(self.seasons_data[-1].get('air_date', '') or '')[:4]
                
                if first_year_full:
                    # 앞 연도의 뒤 2자리 (예: "2019" -> "19")
                    first_year_short = first_year_full[2:]
                    
                    # 💡 [추가된 로직] 마지막 시즌의 연도가 없는 경우 (방영 예정)
                    if not last_year_full:
                        return f"'{first_year_short}~예정"
                    
                    # 시작 연도와 끝 연도가 다를 경우 ('19~'26)
                    elif first_year_full != last_year_full:
                        last_year_short = last_year_full[2:]
                        return f"'{first_year_short}~'{last_year_short}"
                    
                    # 시작 연도와 끝 연도가 같을 경우 (예: 2021년에 2개 시즌이 모두 나온 경우)
                    else:
                        return first_year_full
            except Exception:
                pass
                
        # 2. 시즌이 1개뿐이거나, 위 로직에서 실패했을 경우 기본 최초 방영일 표기
        if self.tmdb_release_date:
            return str(self.tmdb_release_date)[:4]
        return "----"

    # ---------------------------------------------------------
    # 💡 [카드 전용 장르 속성 추가] 상세 페이지는 건드리지 않습니다!
    # ---------------------------------------------------------
    @property
    def card_display_genre(self):
        """카드 오버레이 툴팁용 (다큐, 애니 축약)"""
        genre_str = self.tmdb_genre or self.imdb_genre or "정보 없음"
        return genre_str.replace("다큐멘터리", "다큐").replace("애니메이션", "애니")

    @property
    def card_short_genre(self):
        """카드 하단 노출용 (다큐, 애니 축약)"""
        genre_str = self.tmdb_genre or self.imdb_genre or ""
        if not genre_str:
            return "장르 없음"
        
        first_genre = genre_str.split(',')[0].strip()
        return first_genre.replace("다큐멘터리", "다큐").replace("애니메이션", "애니")

    @property
    def poster_thumb_url(self):
        """그리드 카드용 저용량(w342→w185) 포스터 URL 동적 생성"""
        if self.tmdb_poster_url:
            return self.tmdb_poster_url.replace('/w500/', '/w185/')
        return ""




# 💡1. 커스텀 유저 모델 (이메일 로그인 & username은 닉네임으로 사용)
class User(AbstractUser):
    email = models.EmailField(unique=True)
    
    # 로그인할 때 사용할 기준 필드를 email로 변경
    USERNAME_FIELD = 'email'
    
    # 관리자(createsuperuser) 생성 시 필수로 입력받을 필드
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.username # 닉네임을 출력

# 💡 2. 평점 모델 (영화 또는 TV 시리즈의 평가 기록 통합 저장)
class Rating(models.Model):
  user = models.ForeignKey(
      User, on_delete=models.CASCADE, related_name='ratings'
  )

  # -------------------------------------------------------------------------
  # 🚀 [핵심 수정 1] 영화 vs 시리즈 연결 필드 (둘 중 하나만 채워지므로 null=True 필수!)
  # -------------------------------------------------------------------------
  movie = models.ForeignKey(
      'Movie',
      to_field='tmdb_id',           # 💡 Movie의 tmdb_id와 매핑
      db_column='movie_tmdb_id',    # 💡 DB 테이블 컬럼명 지정
      db_constraint=False,          # 💡 DB 물리적 쇠사슬 끊기!
      on_delete=models.DO_NOTHING,  # 💡 영화가 삭제돼도 평점은 DO NOTHING!
      related_name='ratings',
      null=True,
      blank=True,
      verbose_name='평가한 영화',
  )
  tvseries = models.ForeignKey(
      'TvSeries',
      to_field='tmdb_id',           # 💡 TvSeries의 tmdb_id와 매핑
      db_column='tvseries_tmdb_id', # 💡 DB 테이블 컬럼명 지정
      db_constraint=False,          # 💡 쇠사슬 끊기!
      on_delete=models.DO_NOTHING,  # 💡 DO NOTHING!
      related_name='ratings',
      null=True,
      blank=True,
      verbose_name='평가한 TV 시리즈',
  )

  # 평점: 0.5점 ~ 5.0점 (왓챠/네이버 영화 Style)
  score = models.FloatField(
      validators=[MinValueValidator(0.5), MaxValueValidator(5.0)],
      verbose_name='평점',
  )
  created_at = models.DateTimeField(auto_now_add=True, verbose_name='최초 평가일')

  # 💡 [기존 유지] 감상평 필드
  review = models.TextField(blank=True, null=True, verbose_name='감상평')

  # 💡 [기존 유지] 공개 여부(토글용) & 최신순 정렬을 위한 수정 시간
  is_public = models.BooleanField(default=True, verbose_name='전체 공개 여부')
  updated_at = models.DateTimeField(auto_now=True, verbose_name='최종 수정일')

  class Meta:
    # -------------------------------------------------------------------------
    # 🚀 [핵심 수정 2] 최신 Django 권장 방식인 UniqueConstraint 적용!
    # 💡 한 유저가 "같은 영화" 또는 "같은 시리즈"에 평점을 2개 이상 남기지 못하게 원천 차단합니다.
    # -------------------------------------------------------------------------
    constraints = [
        models.UniqueConstraint(
            fields=['user', 'movie'], name='unique_user_movie_rating'
        ),
        models.UniqueConstraint(
            fields=['user', 'tvseries'], name='unique_user_tvseries_rating'
        ),
    ]
    verbose_name = '사용자 평점'
    verbose_name_plural = '사용자 평점 목록'

  def __str__(self):
    # 🚀 [핵심 수정 3] 영화 평점인지 시리즈 평점인지 안전하게 판별하여 제목 출력 (None 에러 방지)
    if self.movie:
      target_title = f"[영화] {self.movie.tmdb_title}"
    elif self.tvseries:
      target_title = f"[시리즈] {self.tvseries.tmdb_title}"
    else:
      target_title = "[삭제된 작품]"

    return f"{self.user.username} - {target_title} ({self.score}점)"


# 💡 3. 사용자 찜 보관함 (영화 또는 TV 시리즈 찜 통합 저장)
class Watchlist(models.Model):
  user = models.ForeignKey(
      User, on_delete=models.CASCADE, related_name='watchlists'
  )

  # 💡 [수정] 영화 연결 (시리즈 찜할 땐 비어있어야 하므로 null=True 필수)
  movie = models.ForeignKey(
      'Movie',
      to_field='tmdb_id',           
      db_column='movie_tmdb_id',    
      db_constraint=False,          
      on_delete=models.DO_NOTHING,  
      related_name='watchlisted_by',
      null=True, blank=True,
      verbose_name='찜한 영화',
  )
  # 🚀 [신규 추가] TV 시리즈 연결
  tvseries = models.ForeignKey(
      'TvSeries',
      to_field='tmdb_id',           
      db_column='tvseries_tmdb_id', 
      db_constraint=False,          
      on_delete=models.DO_NOTHING,  
      related_name='watchlisted_by',
      null=True, blank=True,
      verbose_name='찜한 TV 시리즈',
  )

  created_at = models.DateTimeField(auto_now_add=True, verbose_name='담은 날짜')

  class Meta:
    # 💡 유저가 같은 영화나 같은 시리즈를 여러 번 중복으로 찜하는 것을 방지합니다.
    constraints = [
        models.UniqueConstraint(
            fields=['user', 'movie'], name='unique_user_movie_watchlist'
        ),
        models.UniqueConstraint(
            fields=['user', 'tvseries'], name='unique_user_tvseries_watchlist'
        ),
    ]
    # 명칭을 '영화'에서 '작품'으로 포괄적으로 변경
    verbose_name = '찜한 작품'
    verbose_name_plural = '찜한 작품 목록'

  def __str__(self):
    # 안전한 제목 출력 판별 로직
    if self.movie:
      target_title = f"[영화] {self.movie.tmdb_title}"
    elif self.tvseries:
      target_title = f"[시리즈] {self.tvseries.tmdb_title}"
    else:
      target_title = "[삭제된 작품]"

    return f"{self.user.username} - {target_title}"



# ==============================================================================
# 💡 예고편 오류 신고 및 관리자 대시보드용 모델
# ==============================================================================
class TrailerReport(models.Model):
    movie = models.ForeignKey('Movie', null=True, blank=True, on_delete=models.CASCADE, related_name='trailer_reports')
    tvseries = models.ForeignKey('TvSeries', null=True, blank=True, on_delete=models.CASCADE, related_name='trailer_reports')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='trailer_reports')
    session_key = models.CharField(max_length=40, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False) # 관리자가 확인 후 숨김(해결) 처리용
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '예고편 오류 신고'
        verbose_name_plural = '예고편 오류 신고 목록'

# 💡 장고 관리자에서 "영화/시리즈별", "유저별"로 묶어서 보기 위한 가상(Proxy) 모델들
class MovieTrailerReport(Movie):
    class Meta:
        proxy = True
        verbose_name = '🎬 영화별 예고편 오류 현황'
        verbose_name_plural = '🎬 영화별 예고편 오류 현황'

class TvTrailerReport(TvSeries):
    class Meta:
        proxy = True
        verbose_name = '📺 시리즈별 예고편 오류 현황'
        verbose_name_plural = '📺 시리즈별 예고편 오류 현황'

class UserTrailerReport(get_user_model()):
    class Meta:
        proxy = True
        verbose_name = '👤 유저별 신고 랭킹 (예고편 오류)'
        verbose_name_plural = '👤 유저별 신고 랭킹 (예고편 오류)'