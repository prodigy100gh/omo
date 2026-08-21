from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count, Q
from django.db import models
from django.forms import Textarea
from collections import Counter
import re
from .models import User, Movie, TvSeries, Rating, Watchlist, TrailerReport, MovieTrailerReport, TvTrailerReport, UserTrailerReport

# ==========================================
# 👤 유저 모델 등록
# ==========================================
# 장고 기본 UserAdmin을 사용하여 비밀번호 해싱 및 권한 관리를 안전하게 처리합니다.
admin.site.register(User, UserAdmin)


# ==========================================
# 💡 [커스텀 필터 1] 장르 (다중 선택 드롭다운)
# ==========================================
class GenreFilter(admin.SimpleListFilter):
    title = '장르'
    parameter_name = 'genre'
    template = 'admin/custom_checkbox_filter.html' # 커스텀 드롭다운 템플릿 연결

    # 1-1. 필터 목록(체크박스 항목) 생성 및 개수 계산
    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        genre_counter = Counter()

        for tmdb_g, imdb_g in qs.values_list('tmdb_genre', 'imdb_genre'):
            genres_found = set()
            if tmdb_g and str(tmdb_g).strip() not in ['None', '']:
                for g in str(tmdb_g).split(','): genres_found.add(g.strip())
            if imdb_g and str(imdb_g).strip() not in ['None', '']:
                for g in str(imdb_g).split(','): genres_found.add(g.strip())
            
            if not genres_found:
                genre_counter['정보 없음'] += 1
            else:
                for g in genres_found: genre_counter[g] += 1

        no_info_count = genre_counter.pop('정보 없음', 0)
        sorted_genres = sorted(genre_counter.items(), key=lambda x: x[1], reverse=True)
        
        results = [(g, f"{g} ({count:,})") for g, count in sorted_genres]
        results.append(('정보 없음', f"정보 없음 ({no_info_count:,})"))
        return results

    # 1-2. 템플릿으로 체크 상태 전달 (다중 선택 지원)
    def choices(self, cl):
        selected_values = self.value().split(',') if self.value() else []
        yield {
            'selected': self.value() is None,
            'query_string': cl.get_query_string({}, [self.parameter_name]),
            'display': '전체 보기 (초기화)',
            'value': '',
        }
        for lookup, title in self.lookup_choices:
            yield {
                'selected': str(lookup) in selected_values,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
                'value': str(lookup),
            }

    # 1-3. 콤마로 연결된 다중 선택값 필터링 쿼리
    def queryset(self, request, queryset):
        val = self.value()
        if not val: return queryset
        
        if val == '정보 없음':
            return queryset.filter(
                (Q(tmdb_genre__isnull=True) | Q(tmdb_genre__exact='')) &
                (Q(imdb_genre__isnull=True) | Q(imdb_genre__exact=''))
            )
            
        selected_genres = val.split(',')
        q = Q()
        for g in selected_genres:
            q |= Q(tmdb_genre__icontains=g.strip()) | Q(imdb_genre__icontains=g.strip())
        return queryset.filter(q)


# ==========================================
# 💡 [커스텀 필터 2] 연령 등급 (다중 선택 드롭다운)
# ==========================================
class RatingFilter(admin.SimpleListFilter):
    title = '연령 등급'
    parameter_name = 'rating'
    template = 'admin/custom_checkbox_filter.html'

    # 2-1. 관람 등급 표준화 및 카운트
    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        rating_counter = Counter()
        
        for r_str in qs.values_list('tmdb_certification_kr', flat=True):
            if not r_str:
                rating_counter['정보 없음'] += 1
                continue
            r_str = str(r_str).strip().upper()
            if r_str in ['ALL', '전체', '전체관람가']: rating_counter['ALL'] += 1
            elif '18' in r_str or '19' in r_str or '청불' in r_str: rating_counter['19'] += 1
            elif '15' in r_str: rating_counter['15'] += 1
            elif '12' in r_str: rating_counter['12'] += 1
            else: rating_counter['정보 없음'] += 1

        # 직관적인 연령대 순서로 고정 배치
        return [
            ('ALL', f"전체 ({rating_counter.get('ALL', 0):,})"),
            ('12', f"12세 ({rating_counter.get('12', 0):,})"),
            ('15', f"15세 ({rating_counter.get('15', 0):,})"),
            ('19', f"19세 ({rating_counter.get('19', 0):,})"),
            ('정보 없음', f"정보 없음 ({rating_counter.get('정보 없음', 0):,})")
        ]

    # 2-2. 다중 선택 템플릿 전달
    def choices(self, cl):
        selected_values = self.value().split(',') if self.value() else []
        yield {
            'selected': self.value() is None,
            'query_string': cl.get_query_string({}, [self.parameter_name]),
            'display': '전체 보기 (초기화)',
            'value': '',
        }
        for lookup, title in self.lookup_choices:
            yield {
                'selected': str(lookup) in selected_values,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
                'value': str(lookup),
            }

    # 2-3. 다중 선택값 필터링 쿼리
    def queryset(self, request, queryset):
        val = self.value()
        if not val: return queryset
        
        selected_ratings = val.split(',')
        q = Q()
        for r in selected_ratings:
            r = r.strip()
            if r == 'ALL': q |= Q(tmdb_certification_kr__icontains='ALL') | Q(tmdb_certification_kr__icontains='전체')
            elif r == '19': q |= Q(tmdb_certification_kr__icontains='18') | Q(tmdb_certification_kr__icontains='19') | Q(tmdb_certification_kr__icontains='청불')
            elif r == '15': q |= Q(tmdb_certification_kr__icontains='15')
            elif r == '12': q |= Q(tmdb_certification_kr__icontains='12')
            elif r == '정보 없음': q |= Q(tmdb_certification_kr__isnull=True) | Q(tmdb_certification_kr__exact='')
        return queryset.filter(q)


# ==========================================
# 💡 [커스텀 필터 3] OTT 플랫폼 (다중 선택 드롭다운)
# ==========================================
class OTTFilter(admin.SimpleListFilter):
    title = 'OTT 서비스'
    parameter_name = 'ott'
    template = 'admin/custom_checkbox_filter.html'

    # 3-1. OTT 추출 및 카운트
    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        ott_counter = Counter()
        
        for ott_data in qs.values_list('tmdb_streaming_providers', flat=True):
            if not ott_data: continue
            if isinstance(ott_data, list):
                for prov in ott_data:
                    name = prov.get('provider_name') or prov.get('name')
                    if name: ott_counter[name.strip()] += 1
            elif isinstance(ott_data, str):
                matches = re.findall(r'"(?:provider_name|name)":\s*"([^"]+)"', ott_data.replace("'", '"'))
                for name in matches: ott_counter[name.strip()] += 1

        # 우선순위 OTT 목록
        preferred_otts = [
            'Netflix', 'netflix', 'Netflix Standard with Ads', 'netflix standard with ads', 
            'TVING', 'tving', 'Coupang Play', 'coupang play', 
            'Wavve', 'wavve', 'Disney Plus', 'disney plus', 'Disney+', 'disney+', 
            'Watcha', 'watcha', 'Apple TV', 'apple tv', 'Apple TV Plus', 'apple tv plus', 'Apple TV+', 'apple tv+', 
            'Amazon Prime Video', 'amazon prime video'
        ]
        
        results = []
        processed = set()
        
        for ott in preferred_otts:
            if ott in ott_counter and ott not in processed:
                count = ott_counter[ott]
                results.append((ott, f"{ott} ({count:,})"))
                processed.add(ott)
        
        remaining_otts = sorted(
            [(ott, count) for ott, count in ott_counter.items() if ott not in processed],
            key=lambda x: x[1], reverse=True
        )
        for ott, count in remaining_otts:
            results.append((ott, f"{ott} ({count:,})"))
            processed.add(ott)
            
        return results

    # 3-2. 다중 선택 템플릿 전달
    def choices(self, cl):
        selected_values = self.value().split(',') if self.value() else []
        yield {
            'selected': self.value() is None,
            'query_string': cl.get_query_string({}, [self.parameter_name]),
            'display': '전체 보기 (초기화)',
            'value': '',
        }
        for lookup, title in self.lookup_choices:
            yield {
                'selected': str(lookup) in selected_values,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
                'value': str(lookup),
            }

    # 3-3. 다중 선택값 필터링 쿼리
    def queryset(self, request, queryset):
        val = self.value()
        if not val: return queryset
        
        selected_otts = val.split(',')
        q = Q()
        for ott in selected_otts:
            q |= Q(tmdb_streaming_providers__icontains=ott.strip())
        return queryset.filter(q)


# ==========================================
# 💡 [커스텀 필터 4] 제작 국가 (다중 선택 드롭다운)
# ==========================================
class CountryFilter(admin.SimpleListFilter):
    title = '제작 국가'
    parameter_name = 'country'
    template = 'admin/custom_checkbox_filter.html'

    # 4-1. 국가 데이터 파싱 및 정렬
    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        country_counter = Counter()
        
        for c_str in qs.values_list('tmdb_production_country_kr', flat=True):
            if c_str and str(c_str).strip() not in ['None', '정보 없음', '']:
                for c in str(c_str).split(','):
                    if c.strip(): country_counter[c.strip()] += 1

        sorted_countries = sorted(country_counter.items(), key=lambda x: x[1], reverse=True)
        results = [(c, f"{c} ({count:,})") for c, count in sorted_countries]
        return results

    # 4-2. 다중 선택 템플릿 전달
    def choices(self, cl):
        selected_values = self.value().split(',') if self.value() else []
        yield {
            'selected': self.value() is None,
            'query_string': cl.get_query_string({}, [self.parameter_name]),
            'display': '전체 보기 (초기화)',
            'value': '',
        }
        for lookup, title in self.lookup_choices:
            yield {
                'selected': str(lookup) in selected_values,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
                'value': str(lookup),
            }

    # 4-3. 다중 선택값 필터링 쿼리
    def queryset(self, request, queryset):
        val = self.value()
        if not val: return queryset
        
        selected_countries = val.split(',')
        q = Q()
        for c in selected_countries:
            q |= Q(tmdb_production_country_kr__icontains=c.strip())
        return queryset.filter(q)


# ==========================================
# 🎬 Movie 모델 어드민 설정
# ==========================================
@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    # 장고 5.0 우측 필터 기본 개수 표시 기능 끄기 (커스텀 개수와 충돌 방지)
    show_facets = admin.ShowFacets.NEVER

    # 💡 [요청 반영] id 와 tmdb_title 사이에 tmdb_id 삽입
    list_display = (
        'id', 
        'tmdb_id',             
        'tmdb_title', 
        'tmdb_original_title', 
        'translated_title',
        'tmdb_release_date', 
        'tmdb_release_date_kr',
        'tmdb_genre', 
        'tmdb_rating', 
        'tmdb_vote_count',
        'tmdb_production_country_kr', 
        'tmdb_original_language',
        'tmdb_certification_kr',        
        'tmdb_certification_us',        
        'tmdb_imdb_id',
        'imdb_genre',                  
        'imdb_rating',
        'imdb_vote_count',             
        'youtube_trailer_url',
        'created_at',
        'updated_at',
    )
    
    search_fields = (
        'tmdb_title', 
        'tmdb_original_title', 
        'translated_title',
        'tmdb_imdb_id',
        'tmdb_director',
        'tmdb_actors',
        '=tmdb_id',
    )
    
    # 위에서 정의한 4가지 커스텀 체크박스 필터 장착
    list_filter = (
        'tmdb_release_date', 
        GenreFilter, 
        RatingFilter,    
        OTTFilter,       
        CountryFilter,
    )
    
    date_hierarchy = 'tmdb_release_date'
    readonly_fields = ('id', 'created_at', 'updated_at')

    list_per_page = 50
    
    # 🚀 2. 상세 폼(Change Form) 필드 순서 자동 재배치 로직
    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        
        # 'id'와 'tmdb_id'를 리스트에서 찾아서 쏙 빼낸 뒤
        if 'id' in fields: fields.remove('id')
        if 'tmdb_id' in fields: fields.remove('tmdb_id')
        
        # 맨 앞에 딱 붙여서 반환합니다!
        return ['id', 'tmdb_id'] + fields

    # 💡 이전 답변에 있던 Media 클래스(css/js 사이드바 제어)는 
    # 드롭다운 방식으로 변경되었으므로 충돌 방지를 위해 제거했습니다.


# ==========================================
# 📺 TvSeries 모델 어드민 설정 (영화와 완벽 동일)
# ==========================================
@admin.register(TvSeries)
class TvSeriesAdmin(admin.ModelAdmin):
    show_facets = admin.ShowFacets.NEVER

    # 💡 [요청 반영] id 와 tmdb_title 사이에 tmdb_id 삽입
    list_display = (
        'id', 
        'tmdb_id',             
        'tmdb_title', 
        'tmdb_original_title', 
        'translated_title',
        'tmdb_release_date', 
        'tmdb_genre', 
        'tmdb_rating', 
        'tmdb_vote_count',
        'tmdb_production_country_kr', 
        'tmdb_original_language',
        'tmdb_certification_kr',        
        'tmdb_certification_us',        
        'tmdb_status',
        'tmdb_imdb_id',
        'imdb_genre',                  
        'imdb_rating',
        'imdb_vote_count',        
        'youtube_trailer_url',
        'created_at',
        'updated_at',
    )
    
    search_fields = (
        'tmdb_title', 
        'tmdb_original_title', 
        'translated_title',
        'tmdb_imdb_id',
        'tmdb_director',
        'tmdb_actors',
        '=tmdb_id',
    )
    
    # 위에서 정의한 4가지 커스텀 체크박스 필터 장착
    list_filter = (
        'tmdb_release_date', 
        GenreFilter, 
        RatingFilter,    
        OTTFilter,       
        CountryFilter,
    )
    
    date_hierarchy = 'tmdb_release_date'
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    list_per_page = 50

    # 상세 페이지 입력칸 크기 확장
    formfield_overrides = {
        models.CharField: {'widget': Textarea(attrs={'rows': 3, 'cols': 60})},
    }

    # 🚀 2. 상세 폼(Change Form) 필드 순서 자동 재배치 로직
    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        
        if 'id' in fields: fields.remove('id')
        if 'tmdb_id' in fields: fields.remove('tmdb_id')
        
        return ['id', 'tmdb_id'] + fields

# ==========================================
# ⭐ Rating 모델 어드민 설정 (유저 감상평)
# ==========================================
@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('user', 'get_content_title', 'score', 'short_review', 'is_public', 'updated_at')
    list_filter = ('score', 'is_public', 'updated_at')
    search_fields = ('user__username', 'movie__tmdb_title', 'review')

    # 1. 🚀 [속도 최적화] N+1 쿼리 방지 (유저, 영화, 시리즈 정보를 한 번의 DB 요청으로 가져옴)
    list_select_related = ('user', 'movie', 'tvseries')
    
    # 2. 🚀 [속도 최적화] 어마어마한 렉의 주범! 드롭다운 메뉴를 돋보기(팝업) 검색으로 변경
    raw_id_fields = ('user', 'movie', 'tvseries')
    
    show_full_result_count = False
    list_per_page = 50

    # 리뷰 텍스트 엔터 치환 및 말줄임 처리
    def short_review(self, obj):
        if obj.review:
            clean_text = obj.review.replace('\n', ' ').replace('\r', ' ').strip()
            return clean_text[:30] + '...' if len(clean_text) > 30 else clean_text
        return "-"
        
    short_review.short_description = '감상평 (미리보기)'

    # 💡 영화인지 시리즈인지 제목을 깔끔하게 출력해주는 커스텀 메서드
    def get_content_title(self, obj):
        if obj.movie:
            return f"🎬 {obj.movie.tmdb_title}"
        elif obj.tvseries:
            return f"📺 {obj.tvseries.tmdb_title}"
        return "-"
    get_content_title.short_description = '평가한 작품'


# ==========================================
# 📌 찜(Watchlist) 관리자 최적화
# ==========================================
@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'get_content_title', 'created_at')
    list_select_related = ('user', 'movie', 'tvseries')
    
    # 🚀 드롭다운 메뉴 무력화
    raw_id_fields = ('user', 'movie', 'tvseries')
    show_full_result_count = False
    list_per_page = 50

    def get_content_title(self, obj):
        if obj.movie:
            return f"🎬 {obj.movie.tmdb_title}"
        elif obj.tvseries:
            return f"📺 {obj.tvseries.tmdb_title}"
        return "-"
    get_content_title.short_description = '찜한 작품'


# 💡 [공통 인라인] 클릭하고 들어가면 "누가 언제 눌렀는지" 보여주는 표
class TrailerReportInline(admin.TabularInline):
    model = TrailerReport
    extra = 0
    readonly_fields = ('user', 'session_key', 'ip_address', 'created_at')
    fields = ('user', 'session_key', 'ip_address', 'created_at', 'is_resolved')
    
    def get_queryset(self, request):
        # 관리자가 아직 해결하지 않은(is_resolved=False) 내역만 보여줍니다.
        return super().get_queryset(request).filter(is_resolved=False).order_by('-created_at')

# 💡 [원클릭 초기화 액션] 리스트에서 체크하고 실행하면 카운트가 0이 됨 (DB 기록 및 예고편 주소는 안전하게 보존)
@admin.action(description="✔️ 선택된 작품의 오류 신고를 모두 해결(숨김) 처리")
def resolve_reports(modeladmin, request, queryset):
    for obj in queryset:
        # 신고 내역만 숨김 처리하고 끝냅니다. (예고편 링크는 절대 건드리지 않음!)
        obj.trailer_reports.filter(is_resolved=False).update(is_resolved=True)

# ==============================================================================
# 💡 영화별 신고 현황 관리자 
# ==============================================================================
@admin.register(MovieTrailerReport)
class MovieTrailerReportAdmin(admin.ModelAdmin):
    # 💡 [추가] 리스트 화면에 reporter_list(신고자 목록) 칸을 추가합니다!
    list_display = ('tmdb_title', 'active_report_count', 'reporter_list') 
    inlines = [TrailerReportInline]
    actions = [resolve_reports]
    search_fields = ('tmdb_title',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(active_reports=Count('trailer_reports', filter=Q(trailer_reports__is_resolved=False))).filter(active_reports__gt=0).order_by('-active_reports')
        
    def active_report_count(self, obj):
        return f"{obj.active_reports}건"
    active_report_count.short_description = "🚨 미해결 신고수"

    # 💡 [핵심] 해당 영화를 신고한 유저들의 닉네임(또는 IP)을 콤마로 묶어서 반환합니다.
    def reporter_list(self, obj):
        reports = obj.trailer_reports.filter(is_resolved=False).select_related('user')
        names = []
        for r in reports:
            if r.user:
                names.append(f"{r.user.username}")
            else:
                names.append(f"비로그인({r.ip_address})")
        return ", ".join(names)
    reporter_list.short_description = "🗣️ 신고자 목록"


# ==============================================================================
# 💡 TV 시리즈별 신고 현황 관리자 
# ==============================================================================
@admin.register(TvTrailerReport)
class TvTrailerReportAdmin(admin.ModelAdmin):
    # 💡 [추가] 리스트 화면에 reporter_list(신고자 목록) 칸을 추가합니다!
    list_display = ('tmdb_title', 'active_report_count', 'reporter_list')
    inlines = [TrailerReportInline]
    actions = [resolve_reports]
    search_fields = ('tmdb_title',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(active_reports=Count('trailer_reports', filter=Q(trailer_reports__is_resolved=False))).filter(active_reports__gt=0).order_by('-active_reports')
        
    def active_report_count(self, obj):
        return f"{obj.active_reports}건"
    active_report_count.short_description = "🚨 미해결 신고수"

    # 💡 [핵심] 해당 시리즈를 신고한 유저들의 닉네임(또는 IP)을 콤마로 묶어서 반환합니다.
    def reporter_list(self, obj):
        reports = obj.trailer_reports.filter(is_resolved=False).select_related('user')
        names = []
        for r in reports:
            if r.user:
                names.append(f"{r.user.username}")
            else:
                names.append(f"비로그인({r.ip_address})")
        return ", ".join(names)
    reporter_list.short_description = "🗣️ 신고자 목록"





# ==============================================================================
# 💡 [유저별 신고 랭킹]
# ==============================================================================
class UserReportInline(admin.TabularInline):
    model = TrailerReport
    extra = 0
    readonly_fields = ('movie', 'tvseries', 'ip_address', 'created_at')
    fields = ('movie', 'tvseries', 'ip_address', 'created_at', 'is_resolved')
    fk_name = 'user'
    def get_queryset(self, request):
        return super().get_queryset(request).order_by('-created_at')

@admin.register(UserTrailerReport)
class UserTrailerReportAdmin(admin.ModelAdmin):
    list_display = ('username', 'total_reports')
    inlines = [UserReportInline]
    search_fields = ('username',)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(total_rep=Count('trailer_reports')).filter(total_rep__gt=0).order_by('-total_rep')
        
    def total_reports(self, obj):
        return f"{obj.total_rep}건"
    total_reports.short_description = "🏆 총 신고 횟수 (누적)"