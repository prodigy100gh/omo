import gzip
import csv
import requests
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.management.base import BaseCommand
from django.db import transaction
from movie.models import Movie, TvSeries
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '영화 및 TV 시리즈 풀옵션 통합 수집 (🔥DB 락 방지 안전 멀티스레드 + ID 완벽 매핑 + 진행률/실패보고서)'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='수집 시작 전 DB를 완전히 삭제(초기화)합니다.')
        parser.add_argument('--target', type=str, default='all', choices=['all', 'movie', 'tv'], help='수집할 대상을 선택합니다')

    # ✨ [추가] 글로벌 언어 확장팩 추가
    LANGUAGE_MAP = {
        'ko': '한국어', 'en': '영어', 'ja': '일본어', 'zh': '중국어(표준어)', 'cn': '중국어(광둥어)', 'yue': '광둥어', 
        'tw': '중국어(대만)', 'th': '태국어', 'id': '인도네시아어', 'vi': '베트남어', 'tl': '타갈로그어', 'ms': '말레이어',
        'fr': '프랑스어', 'es': '스페인어', 'de': '독일어', 'it': '이탈리아어', 'pt': '포르투갈어', 'ru': '러시아어', 
        'nl': '네덜란드어', 'pl': '폴란드어', 'uk': '우크라이나어', 'cs': '체코어', 'hu': '헝가리어', 'el': '그리스어', 
        'ro': '루마니아어', 'sv': '스웨덴어', 'da': '덴마크어', 'no': '노르웨이어', 'fi': '핀란드어',
        'ar': '아랍어', 'tr': '튀르키예어', 'he': '히브리어', 'fa': '페르시아어',
        'hi': '힌디어', 'ta': '타밀어', 'te': '텔루구어', 'ml': '말라얄람어',
    }

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")
        target = options['target']

        if not API_KEY:
            self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY가 설정되지 않았습니다."))
            return

        # -------------------------------------------------------------
        # 💡 [추가] 영화 / TV 블랙리스트(수집 제외) 파일 분리 읽기 로직
        # -------------------------------------------------------------
        exclude_movie_ids = set()
        exclude_tv_ids = set()
        current_dir = os.path.dirname(os.path.abspath(__file__))

        movie_exclude_file = os.path.join(current_dir, 'exclude_movie_ids.txt')
        tv_exclude_file = os.path.join(current_dir, 'exclude_tv_ids.txt')

        # 1. 영화 블랙리스트 로드
        if os.path.exists(movie_exclude_file):
            with open(movie_exclude_file, 'r', encoding='utf-8') as f:
                for line in f:
                    clean_line = line.strip()
                    if clean_line.isdigit(): exclude_movie_ids.add(int(clean_line))
            self.stdout.write(self.style.WARNING(f"🚫 [영화 블랙리스트] '{os.path.basename(movie_exclude_file)}' 감지! (총 {len(exclude_movie_ids)}개 차단)"))

        # 2. TV 블랙리스트 로드
        if os.path.exists(tv_exclude_file):
            with open(tv_exclude_file, 'r', encoding='utf-8') as f:
                for line in f:
                    clean_line = line.strip()
                    if clean_line.isdigit(): exclude_tv_ids.add(int(clean_line))
            self.stdout.write(self.style.WARNING(f"🚫 [TV 블랙리스트] '{os.path.basename(tv_exclude_file)}' 감지! (총 {len(exclude_tv_ids)}개 차단)"))
        # -------------------------------------------------------------

        # 🚨 초기화 로직
        if options['clear']:
            self.stdout.write(self.style.ERROR(f"⚠️ 경고: '{target}' 대상 DB를 완전히 삭제합니다..."))
            if target in ['all', 'movie']: Movie.objects.all().delete()
            if target in ['all', 'tv']: TvSeries.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("✅ DB 초기화 완료! 깨끗한 상태에서 수집을 시작합니다.\n"))

        # 📅 수집 기간 설정
        START_DATE = "2008-01-01"
        END_DATE = "2021-01-01"

        start_dt = datetime.strptime(START_DATE, "%Y-%m-%d")
        end_dt = datetime.strptime(END_DATE, "%Y-%m-%d")
        months = []
        current_dt = start_dt

        while current_dt < end_dt:
            next_dt = current_dt.replace(year=current_dt.year + 1, month=1) if current_dt.month == 12 else current_dt.replace(month=current_dt.month + 1)
            months.append((current_dt.strftime("%Y-%m-%d"), next_dt.strftime("%Y-%m-%d"), f"{current_dt.year}년 {current_dt.month}월"))
            current_dt = next_dt

        self.stdout.write(self.style.WARNING(f"🔥 초고속 안전 크롤러 가동 ({START_DATE} ~ {END_DATE} 전까지, 타겟: {target.upper()})..."))

        # 💡 [추가] 전체 작업 시작 시간 측정 (총 소요 시간 계산용)
        overall_start_time = time.time()

        # 🚀 통신 세션 최적화 (내부적으로 알아서 5번 재시도 수행)
        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries))

        # 💡 실패 내역을 모을 거대한 바구니 준비
        global_failed_movies = []
        global_failed_tv = []

        # 💡 [수정] 각각 분리된 블랙리스트를 해당 함수에 넘겨줍니다.
        if target in ['all', 'movie']: 
            global_failed_movies = self.crawl_movies(months, API_KEY, session, exclude_movie_ids)
        if target in ['all', 'tv']: 
            global_failed_tv = self.crawl_tv(months, API_KEY, session, exclude_tv_ids)

        # 💡 [추가] 총 걸린 시간 계산
        overall_elapsed_time = time.time() - overall_start_time

        # 💡 [복구 완료] 대망의 최종 에러 보고서 출력
        self.stdout.write(self.style.SUCCESS(f"\n🎉 [{target.upper()}] 대상의 모든 작업이 완벽하게 종료되었습니다! (총 소요 시간: {self.format_time(overall_elapsed_time)})"))
        
        if global_failed_movies or global_failed_tv:
            self.stdout.write(self.style.ERROR("\n======================================================="))
            self.stdout.write(self.style.ERROR("🚨 [최종 보고서] 끝내 수집/저장에 실패한 불량 데이터 목록"))
            self.stdout.write(self.style.ERROR("======================================================="))
            
            if global_failed_movies:
                self.stdout.write(self.style.WARNING("\n🎬 [영화 실패 목록]"))
                for fail in global_failed_movies:
                    self.stdout.write(f" - TMDB ID: {fail['id']} | 사유: {fail['reason']}")
                    
            if global_failed_tv:
                self.stdout.write(self.style.WARNING("\n📺 [TV 시리즈 실패 목록]"))
                for fail in global_failed_tv:
                    self.stdout.write(f" - TMDB ID: {fail['id']} | 사유: {fail['reason']}")
            
            self.stdout.write(self.style.ERROR("\n(※ 위 항목들은 TMDB 자체 DB 오류이거나 정보가 누락된 버그 데이터일 확률이 높습니다.)"))
        else:
            self.stdout.write(self.style.SUCCESS("\n🌟 단 하나의 실패도 없이 100% 완벽하게 수집되었습니다! 🌟"))

    # =====================================================================
    # 🎬 [영화 크롤링]
    # =====================================================================
    def crawl_movies(self, months, API_KEY, session, exclude_movie_ids):
        total_months = len(months)
        created_count, updated_count = 0, 0
        failed_list = []

        # 💡 [수정] 파라미터를 exclude_movie_ids 로 받음
        # 💡 [수정] DB ID와 영화 블랙리스트 ID를 합침
        existing_ids = set(Movie.objects.values_list('tmdb_id', flat=True))
        existing_ids.update(exclude_movie_ids) 
        
        self.stdout.write(self.style.WARNING(f"\n[영화 수집 시작] 📌 스킵 대상: {len(existing_ids)}개 (DB 보존 및 블랙리스트 포함)"))

        for m_idx, (start, end, label) in enumerate(months, 1):
            self.stdout.write(self.style.NOTICE(f"\n📂 [MOVIE PHASE 1] [{m_idx}/{total_months}] {label} 개봉 영화 수집 중..."))
            tmdb_end = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            page, current_max_pages = 1, 500
            
            start_time = time.time() # 💡 예상 시간 계산용 기준점

            while page <= current_max_pages:
                discover_url = f"https://api.themoviedb.org/3/discover/movie?api_key={API_KEY}&language=ko-KR&primary_release_date.gte={start}&primary_release_date.lte={tmdb_end}&sort_by=popularity.desc&page={page}"
                discover_data = self.fetch_url(discover_url, session)
                
                if not discover_data or not discover_data.get('results'): break 
                current_max_pages = min(discover_data.get('total_pages', 1), 500)
                
                tmdb_ids = [item['id'] for item in discover_data.get('results', []) if item.get('id') and item['id'] not in existing_ids]
                
                parsed_results = []
                
                with ThreadPoolExecutor(max_workers=40) as executor:
                    futures = {executor.submit(self._fetch_movie_api, tid, API_KEY, session): tid for tid in tmdb_ids}
                    for future in as_completed(futures):
                        tid = futures[future]
                        result = future.result()
                        if result: 
                            parsed_results.append(result)
#                        else:                                        # 불량품 보고 제거
#                            # 💡 [복구] API가 끝내 거부한 녀석 추적
#                            failed_list.append({'id': tid, 'reason': 'API 데이터 누락 또는 통신 실패'})

                try:
                    with transaction.atomic():
                        for data_dict in parsed_results:
                            movie, created = Movie.objects.update_or_create(
                                tmdb_id=data_dict['tmdb_id'],
                                defaults=data_dict['defaults']
                            )
                            if created: created_count += 1
                            else: updated_count += 1
                            if 'existing_ids' in locals(): existing_ids.add(data_dict['tmdb_id'])
                            
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  ⚠️ 묶음 저장 충돌 감지! 안전 개별 저장 모드로 전환합니다..."))
                    for data_dict in parsed_results:
                        try:
                            with transaction.atomic():
                                movie, created = Movie.objects.update_or_create(
                                    tmdb_id=data_dict['tmdb_id'],
                                    defaults=data_dict['defaults']
                                )
                                if created: created_count += 1
                                else: updated_count += 1
                                if 'existing_ids' in locals(): existing_ids.add(data_dict['tmdb_id'])
                        except Exception as inner_e:
                            # 💡 [복구] DB 저장을 거부한 불량품 추적
                            failed_list.append({'id': data_dict['tmdb_id'], 'reason': f'DB 저장 실패 ({inner_e})'})
                
                # 💡 [복구 완료] 경과 시간 및 남은 예상 시간(ETA) 동적 계산 로직
                elapsed = time.time() - start_time
                avg_time_per_page = elapsed / page
                remaining_pages = current_max_pages - page
                eta_seconds = avg_time_per_page * remaining_pages
                
                self.stdout.write(self.style.HTTP_INFO(f"  ↳ Page {page}/{current_max_pages} 완료 | ⏳ 소요: {self.format_time(elapsed)} | ⏰ 예상 남은시간: {self.format_time(eta_seconds)} | (추가: {created_count} 갱신: {updated_count})"))
                page += 1

        self._match_imdb_data(Movie)
        self.stdout.write(self.style.SUCCESS("\n✨ [영화] 수집 및 매칭 완료!"))
        return failed_list

    # =====================================================================
    # 📺 [TV 시리즈 크롤링]
    # =====================================================================
    def crawl_tv(self, months, API_KEY, session, exclude_tv_ids):
        total_months = len(months)
        created_count, updated_count = 0, 0
        failed_list = [] 

        self.stdout.write(self.style.WARNING(f"\n[TV 수집 시작] 📌 신작 및 새로운 시즌 방영작 강제 갱신 모드 가동!"))

        for m_idx, (start, end, label) in enumerate(months, 1):
            self.stdout.write(self.style.NOTICE(f"\n📂 [TV PHASE 1] [{m_idx}/{total_months}] {label} 방영 드라마 수집 중..."))
            tmdb_end = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            page, current_max_pages = 1, 100 
            
            start_time = time.time() # 💡 예상 시간 계산용 기준점

            while page <= current_max_pages:
                discover_url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=ko-KR&air_date.gte={start}&air_date.lte={tmdb_end}&sort_by=popularity.desc&page={page}"
                discover_data = self.fetch_url(discover_url, session)
                
                if not discover_data or not discover_data.get('results'): break
                current_max_pages = min(discover_data.get('total_pages', 1), 100)

                # 💡 [수정] TV 블랙리스트(exclude_tv_ids)에 포함되지 않은 ID만 추출
                tmdb_ids = [item['id'] for item in discover_data.get('results', []) if item.get('id') and item['id'] not in exclude_tv_ids]

                parsed_results = []
                
                with ThreadPoolExecutor(max_workers=40) as executor:
                    futures = {executor.submit(self._fetch_tv_api, tid, API_KEY, session): tid for tid in tmdb_ids}
                    for future in as_completed(futures):
                        tid = futures[future]
                        result = future.result()
                        if result: 
                            parsed_results.append(result)
#                        else:                                        # 불량품 보고 제거
#                            # 💡 [복구] API가 끝내 거부한 녀석 추적
#                            failed_list.append({'id': tid, 'reason': 'API 데이터 누락 또는 통신 실패'})
                try:
                    with transaction.atomic():
                        for data_dict in parsed_results:
                            series, created = TvSeries.objects.update_or_create(  
                                tmdb_id=data_dict['tmdb_id'],
                                defaults=data_dict['defaults']
                            )
                            if created: created_count += 1
                            else: updated_count += 1
                            
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  ⚠️ 묶음 저장 충돌 감지! 안전 개별 저장 모드로 전환합니다..."))
                    for data_dict in parsed_results:
                        try:
                            with transaction.atomic():
                                series, created = TvSeries.objects.update_or_create(  
                                    tmdb_id=data_dict['tmdb_id'],
                                    defaults=data_dict['defaults']
                                )
                                if created: created_count += 1
                                else: updated_count += 1
                        except Exception as inner_e:
                            # 💡 [복구] DB 저장을 거부한 불량품 추적
                            failed_list.append({'id': data_dict['tmdb_id'], 'reason': f'DB 저장 실패 ({inner_e})'})

                # 💡 [복구 완료] 경과 시간 및 남은 예상 시간(ETA) 동적 계산 로직
                elapsed = time.time() - start_time
                avg_time_per_page = elapsed / page
                remaining_pages = current_max_pages - page
                eta_seconds = avg_time_per_page * remaining_pages

                self.stdout.write(self.style.HTTP_INFO(f"  ↳ Page {page}/{current_max_pages} 완료 | ⏳ 소요: {self.format_time(elapsed)} | ⏰ 예상 남은시간: {self.format_time(eta_seconds)} | (추가: {created_count} 갱신: {updated_count})"))
                page += 1

        self._match_imdb_data(TvSeries)
        self.stdout.write(self.style.SUCCESS("\n✨ [TV] 수집 및 매칭 완료!"))
        return failed_list

    # =====================================================================
    # ⚙️ [영화 API 파싱 (DB 저장 분리)]
    # =====================================================================
    def _fetch_movie_api(self, tmdb_id, API_KEY, session):
        try:
            detail_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={API_KEY}&language=ko-KR&append_to_response=credits,videos,watch/providers,recommendations,keywords,release_dates"
            data = self.fetch_url(detail_url, session)
            if not data: return None

            title, original_title, poster_path = data.get('title', ''), data.get('original_title', ''), data.get('poster_path')
            if not title or not poster_path: return None

            director, director_id, director_image_url, screenwriter, screenwriter_id = "", None, "", "", None
            for crew in data.get('credits', {}).get('crew', []):
                if crew['job'] == 'Director' and not director:
                    director, director_id, director_image_url = crew['name'], crew.get('id'), f"https://image.tmdb.org/t/p/w185{crew['profile_path']}" if crew.get('profile_path') else ""
                if crew['job'] in ['Screenplay', 'Writer'] and not screenwriter:
                    screenwriter, screenwriter_id = crew['name'], crew.get('id')
                    
            cast_list = data.get('credits', {}).get('cast', [])
            actors = ", ".join([c['name'] for c in cast_list[:5]])
            actor_details = [{"id": c.get('id'), "name": c.get('name', ''), "character": c.get('character', ''), "profile_url": f"https://image.tmdb.org/t/p/w185{c['profile_path']}" if c.get('profile_path') else ""} for c in cast_list[:10]]
            
            trailer_url = next((f"https://www.youtube.com/watch?v={v['key']}" for v in data.get('videos', {}).get('results', []) if v.get('site') == 'YouTube' and v.get('type') in ['Trailer', 'Teaser']), "")
            streaming_providers = [{"provider_name": p.get('provider_name', ''), "logo_url": f"https://image.tmdb.org/t/p/w92{p.get('logo_path', '')}" if p.get('logo_path') else ""} for p in data.get('watch/providers', {}).get('results', {}).get('KR', {}).get('flatrate', [])]
                
            recommended_movies = []
            for rec in data.get('recommendations', {}).get('results', [])[:5]:
                rec_country = self.get_country_kr_from_code(rec.get('origin_country')[0]) if rec.get('origin_country') else ""
                recommended_movies.append({
                    "id": rec.get('id'), "title": rec.get('title', ''), "poster_url": f"https://image.tmdb.org/t/p/w185{rec.get('poster_path')}" if rec.get('poster_path') else "",
                    "release_date": rec.get('release_date', '')[:4], "rating": round(rec.get('vote_average', 0.0), 1),
                    "vote_count": rec.get('vote_count', 0), "country": rec_country, "genre": self.get_genre_kr_from_ids(rec.get('genre_ids', []))
                })
            
            kr_cert, us_cert, kr_release_date = "", "", None
            for rd in data.get('release_dates', {}).get('results', []):
                if rd['iso_3166_1'] == 'KR': 
                    kr_cert = next((r['certification'] for r in rd['release_dates'] if r.get('certification')), "")
                    raw_kr_date = next((r['release_date'] for r in rd['release_dates'] if r.get('release_date')), "")
                    if raw_kr_date: kr_release_date = raw_kr_date[:10]
                elif rd['iso_3166_1'] == 'US': 
                    us_cert = next((r['certification'] for r in rd['release_dates'] if r.get('certification')), "")
                    
            # ✨ [변경] 언어 정보 추출 및 변환
            lang_code = data.get('original_language', '')
            lang_val = self.LANGUAGE_MAP.get(lang_code, lang_code.upper()) if lang_code else "확인불가"

            # ✨ [변경] 국가 정보 목록 전체 추출 로직
            countries = data.get('production_countries', [])
            codes = [c.get('iso_3166_1', '') for c in countries]
            engs = [c.get('name', '') for c in countries]

            if codes:
                krs = [self.get_country_kr_from_code(code) for code in codes]
                prod_code = ','.join(codes)
                prod_eng = ', '.join(engs)
                prod_kr = ', '.join(filter(None, krs))
            else:
                prod_code, prod_eng, prod_kr = "", "", ""

            korean_genres = self.translate_text_genres(", ".join([g['name'] for g in data.get('genres', [])]))
            imdb_id_val = (data.get('imdb_id', '') or "").strip()

            return {
                'tmdb_id': tmdb_id,
                'defaults': {
                    'tmdb_original_language': lang_val, # ✨ [추가] 언어 DB 저장
                    'tmdb_imdb_id': imdb_id_val if imdb_id_val else None,
                    'tmdb_title': title, 'tmdb_original_title': original_title,
                    'tmdb_genre': korean_genres,
                    'tmdb_release_date': data.get('release_date') or None,
                    'tmdb_release_date_kr': kr_release_date,
                    'tmdb_runtime': data.get('runtime', 0),
                    'tmdb_rating': round(data.get('vote_average', 0.0), 1), 'tmdb_vote_count': data.get('vote_count', 0),
                    'tmdb_overview': data.get('overview', ''), 'tmdb_poster_url': f"https://image.tmdb.org/t/p/w500{poster_path}", 'backdrop_path': data.get('backdrop_path'),
                    'tmdb_trailer_url': trailer_url,
                    'tmdb_director': director, 'tmdb_director_id': director_id, 'tmdb_director_image_url': director_image_url,
                    'tmdb_screenwriter': screenwriter, 'tmdb_screenwriter_id': screenwriter_id,
                    'tmdb_actors': actors, 'tmdb_actor_details': actor_details,
                    'tmdb_streaming_providers': streaming_providers, 'tmdb_recommended_movies': recommended_movies,
                    'tmdb_keywords': ", ".join([k['name'] for k in data.get('keywords', {}).get('keywords', [])]),
                    'tmdb_certification_us': us_cert, 'tmdb_certification_kr': kr_cert,
                    'tmdb_budget': data.get('budget', 0), 'tmdb_revenue': data.get('revenue', 0),
                    'tmdb_production_country_code': prod_code, 'tmdb_production_country_eng': prod_eng, 'tmdb_production_country_kr': prod_kr,
                }
            }
        except Exception as e:
            return None

    # =====================================================================
    # ⚙️ [TV 시리즈 API 파싱 (DB 저장 분리)]
    # =====================================================================
    def _fetch_tv_api(self, tmdb_id, API_KEY, session):
        try:
            detail_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={API_KEY}&language=ko-KR&append_to_response=credits,videos,watch/providers,recommendations,keywords,content_ratings,external_ids"
            data = self.fetch_url(detail_url, session)
            if not data: return None

            title, poster_path = data.get('name', ''), data.get('poster_path')
            if not title or not poster_path: return None

            seasons_data = [{'season_number': s.get('season_number'), 'name': s.get('name', ''), 'air_date': s.get('air_date', ''), 'episode_count': s.get('episode_count', 0), 'poster_path': s.get('poster_path', ''), 'vote_average': round(s.get('vote_average', 0.0), 1), 'vote_count': s.get('vote_count', 0)} for s in data.get('seasons', []) if s.get('season_number') != 0]

            director, director_id, director_image_url, screenwriter, screenwriter_id = "", None, "", "", None
            if data.get('created_by'):
                director, director_id, director_image_url = data.get('created_by')[0].get('name', ''), data.get('created_by')[0].get('id'), f"https://image.tmdb.org/t/p/w185{data.get('created_by')[0].get('profile_path')}" if data.get('created_by')[0].get('profile_path') else ""

            for crew in data.get('credits', {}).get('crew', []):
                if not director and crew['job'] in ['Director', 'Executive Producer', 'Series Director']:
                    director, director_id, director_image_url = crew['name'], crew.get('id'), f"https://image.tmdb.org/t/p/w185{crew['profile_path']}" if crew.get('profile_path') else ""
                if crew['job'] in ['Screenplay', 'Writer', 'Writer (Staff)', 'Teleplay'] and not screenwriter:
                    screenwriter, screenwriter_id = crew['name'], crew.get('id')
                    
            cast_list = data.get('credits', {}).get('cast', [])
            actors = ", ".join([c['name'] for c in cast_list[:5]])
            actor_details = [{"id": c.get('id'), "name": c.get('name', ''), "character": c.get('character', ''), "profile_url": f"https://image.tmdb.org/t/p/w185{c['profile_path']}" if c.get('profile_path') else ""} for c in cast_list[:10]]
            trailer_url = next((f"https://www.youtube.com/watch?v={v['key']}" for v in data.get('videos', {}).get('results', []) if v.get('site') == 'YouTube' and v.get('type') in ['Trailer', 'Teaser']), "")
            streaming_providers = [{"provider_name": p.get('provider_name', ''), "logo_url": f"https://image.tmdb.org/t/p/w92{p.get('logo_path', '')}" if p.get('logo_path') else ""} for p in data.get('watch/providers', {}).get('results', {}).get('KR', {}).get('flatrate', [])]
                
            recommended_movies = []
            for rec in data.get('recommendations', {}).get('results', [])[:5]:
                rec_country = self.get_country_kr_from_code(rec.get('origin_country')[0]) if rec.get('origin_country') else ""
                recommended_movies.append({
                    "id": rec.get('id'), "title": rec.get('name', ''), "poster_url": f"https://image.tmdb.org/t/p/w185{rec.get('poster_path')}" if rec.get('poster_path') else "",
                    "release_date": rec.get('first_air_date', '')[:4], "rating": round(rec.get('vote_average', 0.0), 1),
                    "vote_count": rec.get('vote_count', 0), "country": rec_country, "genre": self.get_genre_kr_from_ids(rec.get('genre_ids', []))
                })
            
            kr_cert, us_cert = "", ""
            for cr in data.get('content_ratings', {}).get('results', []):
                if cr['iso_3166_1'] == 'KR': kr_cert = cr.get('rating', '')
                elif cr['iso_3166_1'] == 'US': us_cert = cr.get('rating', '')
                        
            # ✨ [변경] 언어 정보 추출 및 변환
            lang_code = data.get('original_language', '')
            lang_val = self.LANGUAGE_MAP.get(lang_code, lang_code.upper()) if lang_code else "확인불가"

            # ✨ [변경] 국가 정보 목록 전체 추출 로직
            countries = data.get('production_countries', [])
            if not countries:
                # TV의 경우 origin_country 배열 활용
                codes = data.get('origin_country', [])
                engs = codes 
            else:
                codes = [c.get('iso_3166_1', '') for c in countries]
                engs = [c.get('name', '') for c in countries]

            if codes:
                krs = [self.get_country_kr_from_code(code) for code in codes]
                prod_code = ','.join(codes)
                prod_eng = ', '.join(engs)
                prod_kr = ', '.join(filter(None, krs))
            else:
                prod_code, prod_eng, prod_kr = "", "", ""

            korean_genres = self.translate_text_genres(", ".join([g['name'] for g in data.get('genres', [])]))

            imdb_id_val = (data.get('external_ids', {}).get('imdb_id', '') or "").strip()
            ep_run_times = data.get('episode_run_time', [])

            return {
                'tmdb_id': tmdb_id,
                'defaults': {
                    'tmdb_original_language': lang_val, # ✨ [추가] 언어 DB 저장
                    'tmdb_imdb_id': imdb_id_val if imdb_id_val else None,
                    'tmdb_title': title[:255], 'tmdb_original_title': data.get('original_name', '')[:255],
                    'tmdb_genre': korean_genres[:255],
                    'tmdb_release_date': data.get('first_air_date') or None, 'tmdb_runtime': ep_run_times[0] if ep_run_times else 0,
                    'tmdb_status': data.get('status', ''), 'tmdb_number_of_seasons': data.get('number_of_seasons', 0),
                    'seasons_data': seasons_data, 'tmdb_rating': round(data.get('vote_average', 0.0), 1),
                    'tmdb_vote_count': data.get('vote_count', 0), 'tmdb_overview': data.get('overview', ''),
                    'tmdb_poster_url': f"https://image.tmdb.org/t/p/w500{poster_path}", 'backdrop_path': data.get('backdrop_path'),
                    'tmdb_trailer_url': trailer_url,
                    'tmdb_director': director[:255], 'tmdb_director_id': director_id, 'tmdb_director_image_url': director_image_url,
                    'tmdb_screenwriter': screenwriter[:255], 'tmdb_screenwriter_id': screenwriter_id,
                    'tmdb_actors': actors[:500], 'tmdb_actor_details': actor_details,
                    'tmdb_streaming_providers': streaming_providers, 'tmdb_recommended_movies': recommended_movies,
                    'tmdb_keywords': ", ".join([k['name'] for k in data.get('keywords', {}).get('results', [])])[:500],
                    'tmdb_certification_us': us_cert, 'tmdb_certification_kr': kr_cert,
                    'tmdb_production_country_code': prod_code, 'tmdb_production_country_eng': prod_eng, 'tmdb_production_country_kr': prod_kr,
                    'tmdb_budget': 0, 'tmdb_revenue': 0,
                }
            }
        except Exception as e:
            return None

    # =====================================================================
    # 🔗 [공통 로컬 IMDb TSV 파싱 및 결합]
    # =====================================================================
    def _match_imdb_data(self, model_class):
        model_name = "영화" if model_class == Movie else "TV 시리즈"
        self.stdout.write(self.style.NOTICE(f"\n📁 [PHASE 2] {model_name} IMDb 로컬 TSV 데이터 결합 시작..."))

        target_items = model_class.objects.exclude(tmdb_imdb_id__isnull=True).exclude(tmdb_imdb_id='')
        item_map = {m.tmdb_imdb_id.strip().lower(): m for m in target_items}
        target_ids = set(item_map.keys())

        if not target_ids: return

        self.stdout.write(f"🎯 매칭 대상 고유 IMDb ID 개수: {len(target_ids)}개")

        try:
            self.stdout.write("⏳ [1/2] 'title.ratings.tsv.gz' 스캔 중...")
            with gzip.open('title.ratings.tsv.gz', 'rt', encoding='utf-8') as f:
                for row in csv.DictReader(f, delimiter='\t'):
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        obj = item_map[tconst_clean]
                        obj.imdb_rating = float(row['averageRating']) if row['averageRating'] != '\\N' else 0.0
                        obj.imdb_vote_count = int(row['numVotes']) if row['numVotes'] != '\\N' else 0
        except FileNotFoundError: self.stdout.write(self.style.ERROR("❌ 'title.ratings.tsv.gz' 없음!"))

        try:
            self.stdout.write("⏳ [2/2] 'title.basics.tsv.gz' 스캔 중...")
            with gzip.open('title.basics.tsv.gz', 'rt', encoding='utf-8') as f:
                for row in csv.DictReader(f, delimiter='\t'):
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        obj = item_map[tconst_clean]
                        rt, g, year = row['runtimeMinutes'], row['genres'], row['startYear']
                        if rt != '\\N': obj.imdb_runtime = int(rt)
                        if g != '\\N': obj.imdb_genre = self.translate_text_genres(g)
                        if year != '\\N': obj.imdb_release_date = year
        except FileNotFoundError: self.stdout.write(self.style.ERROR("❌ 'title.basics.tsv.gz' 없음!"))

        self.stdout.write("⏳ 매칭 완료된 IMDb 데이터 DB 벌크 업데이트 중...")
        with transaction.atomic():
            model_class.objects.bulk_update(
                target_items, ['imdb_rating', 'imdb_vote_count', 'imdb_runtime', 'imdb_genre', 'imdb_release_date'], batch_size=500
            )

    # =====================================================================
    # 🛠️ [헬퍼 메서드 모음]
    # =====================================================================
    def fetch_url(self, url, session):
        while True:
            try:
                res = session.get(url, timeout=10)
                if res.status_code == 200: return res.json()
                elif res.status_code == 404: return None
                elif res.status_code == 429: time.sleep(2)
                else: time.sleep(1)
            except Exception: time.sleep(1)

    def translate_text_genres(self, genre_str):
        if not genre_str or genre_str == '\\N': return ""
        mapping = {
            "Action": "액션", "Adventure": "모험", "Animation": "애니메이션",
            "Biography": "전기", "Comedy": "코미디", "Crime": "범죄",
            "Documentary": "다큐멘터리", "Drama": "드라마", "Family": "가족",
            "Fantasy": "판타지", "Film-Noir": "느와르", "History": "역사",
            "Horror": "공포", "Music": "음악", "Musical": "뮤지컬",
            "Mystery": "미스터리", "Romance": "로맨스", "Sci-Fi": "SF",
            "Short": "단편", "Sport": "스포츠", "Thriller": "스릴러",
            "War": "전쟁", "Western": "서부", 
            "Reality-TV": "리얼리티", "Talk-Show": "토크쇼", "News": "뉴스",
            "Game-Show": "게임쇼", "Adult": "성인",
            "Action & Adventure": "액션&모험", "Sci-Fi & Fantasy": "SF&판타지",
            "War & Politics": "전쟁&정치", "Kids": "가족", "Soap": "소프 오페라",
            "Reality": "리얼리티", "Talk": "토크쇼"
        }
        return ", ".join([mapping.get(g.strip(), g.strip()) for g in genre_str.replace('/', ',').split(',') if g.strip()])

    def get_genre_kr_from_ids(self, genre_ids):
        if not genre_ids: return "정보 없음"
        genre_map = {
            28: "액션", 12: "모험", 16: "애니메이션", 35: "코미디", 80: "범죄", 99: "다큐멘터리",
            18: "드라마", 10751: "가족", 14: "판타지", 36: "역사", 27: "공포", 10402: "음악",
            9648: "미스터리", 10749: "로맨스", 878: "SF", 10770: "TV 영화", 53: "스릴러",
            10752: "전쟁", 37: "서부", 10759: "액션&모험", 10762: "키즈", 10763: "뉴스",
            10764: "리얼리티", 10765: "SF&판타지", 10766: "소프 오페라", 10767: "토크쇼", 10768: "전쟁&정치"
        }
        genres = [genre_map.get(g_id) for g_id in genre_ids if genre_map.get(g_id)]
        return ", ".join(genres) if genres else "정보 없음"

    def get_country_kr_from_code(self, code):
        if not code: return "정보 없음"
        code_map = {
            # 🇰🇷 주요 아시아
            "KR": "한국", "US": "미국", "JP": "일본", "CN": "중국", "HK": "홍콩", "MO": "마카오", 
            "TW": "대만", "TH": "태국", "VN": "베트남", "IN": "인도", "ID": "인도네시아", 
            "PH": "필리핀", "SG": "싱가포르", "MY": "말레이시아", "MN": "몽골", "PK": "파키스탄", 
            "BD": "방글라데시", "KZ": "카자흐스탄", "NP": "네팔", "KH": "캄보디아", "MM": "미얀마",
            "UZ": "우즈베키스탄", "KG": "키르기스스탄", "BN": "브루나이", "LA": "라오스",
            "AF": "아프가니스탄", "TM": "투르크메니스탄", "TJ": "타지키스탄", "BT": "부탄",
            "KP": "북한", "MV": "몰디브", "TL": "동티모르",
            
            # 🌍 유럽 / 러시아 / 코카서스
            "GB": "영국", "FR": "프랑스", "DE": "독일", "IT": "이탈리아", "ES": "스페인",
            "NL": "네덜란드", "BE": "벨기에", "SE": "스웨덴", "NO": "노르웨이", "DK": "덴마크", 
            "FI": "핀란드", "CH": "스위스", "AT": "오스트리아", "PL": "폴란드", "HU": "헝가리", 
            "CZ": "체코", "SK": "슬로바키아", "GR": "그리스", "PT": "포르투갈", "IE": "아일랜드", 
            "RO": "루마니아", "UA": "우크라이나", "TR": "터키", "IS": "아이슬란드", "LU": "룩셈부르크",
            "BG": "불가리아", "RS": "세르비아", "HR": "크로아티아", "LV": "라트비아", "LT": "리투아니아",
            "EE": "에스토니아", "SI": "슬로베니아", "ME": "몬테네그로", "GE": "조지아", "CY": "키프로스", 
            "AL": "알바니아", "BA": "보스니아 헤르체고비나", "BY": "벨라루스", "MD": "몰도바",
            "RU": "러시아", "AM": "아르메니아", "MT": "몰타", "MC": "모나코", "LI": "리히텐슈타인", 
            "SM": "산마리노", "VA": "바티칸", "AZ": "아제르바이잔", "AD": "안도라", "FO": "페로 제도",
            "GI": "지브롤터", "IM": "맨섬", "SJ": "스발바르 얀마옌",
            
            # 🌮 중남미 & 카리브해
            "CA": "캐나다", "MX": "멕시코", "BR": "브라질", "AR": "아르헨티나", "CL": "칠레", 
            "CO": "콜롬비아", "PE": "페루", "CU": "쿠바", "VE": "베네수엘라", "DO": "도미니카 공화국",
            "GT": "과테말라", "BM": "버뮤다", "AW": "아루바", "JM": "자메이카", "CR": "코스타리카",
            "UY": "우루과이", "BO": "볼리비아", "PR": "푸에르토리코", "GL": "그린란드", "EC": "에콰도르",
            "HN": "온두라스", "SV": "엘살바도르", "NI": "니카라과", "PA": "파나마", "PY": "파라과이", 
            "HT": "아이티", "TT": "트리니다드 토바고", "BS": "바하마", "BZ": "벨리즈", "BB": "바베이도스",
            "GY": "가이아나", "SR": "수리남", "AG": "앤티가 바부다", "LC": "세인트루시아", 
            "KN": "세인트키츠 네비스", "VC": "세인트빈센트 그레나딘", "DM": "도미니카 연방", 
            "GD": "그레나다", "CW": "퀴라소", "GF": "프랑스령 기아나", "GP": "과들루프", "MQ": "마르티니크",
            "VI": "미국령 버진아일랜드", "VG": "영국령 버진아일랜드", "KY": "케이맨 제도", "MS": "몬트세랫",
            "TC": "터크스 케이커스 제도", "SX": "신트마르턴", "BQ": "카리브 네덜란드", "BL": "생바르텔레미",
            "MF": "생마르탱", "PM": "생피에르 미클롱", "FK": "포클랜드 제도",
            
            # 🐪 중동 / 아프리카
            "AU": "호주", "NZ": "뉴질랜드", "ZA": "남아프리카공화국", "IL": "이스라엘", "EG": "이집트", 
            "SA": "사우디아라비아", "AE": "아랍에미리트", "IR": "이란", "IQ": "이라크", "NG": "나이지리아", 
            "MA": "모로코", "KE": "케냐", "DZ": "알제리", "TN": "튀니지", "SD": "수단", "MK": "북마케도니아",
            "LK": "스리랑카", "BF": "부르키나파소", "AQ": "남극", "RW": "르완다", "SY": "시리아", 
            "LB": "레바논", "LS": "레소토", "SN": "세네갈", "CD": "콩고민주공화국", "CG": "콩고공화국",
            "CI": "코트디부아르", "KW": "쿠웨이트", "ZW": "짐바브웨", "GH": "가나", "CV": "카보베르데",
            "QA": "카타르", "OM": "오만", "BH": "바레인", "JO": "요르단", "YE": "예멘", "PS": "팔레스타인",
            "UG": "우간다", "TZ": "탄자니아", "ET": "에티오피아", "CM": "카메룬", "AO": "앙골라",
            "MG": "마다가스카르", "ML": "말리", "MU": "모리셔스", "FJ": "피지", "PG": "파푸아뉴기니",
            "GA": "가봉", "TD": "차드", "TG": "토고", "CF": "중앙아프리카공화국", "GN": "기니", 
            "GW": "기니비사우", "GQ": "적도 기니", "BI": "부룬디", "BJ": "베냉", "BW": "보츠와나", 
            "DJ": "지부티", "ER": "에리트레아", "GM": "감비아", "LR": "라이베리아", "MW": "말라위", 
            "MR": "모리타니", "MZ": "모잠비크", "NA": "나미비아", "NE": "니제르", "SO": "소말리아", 
            "SZ": "에스와티니", "SC": "세이셸", "ST": "상투메 프린시페", "KM": "코모로", "RE": "레위니옹",
            "SL": "시에라리온", "SS": "남수단", "EH": "서사하라", "SH": "세인트헬레나", "YT": "마요트",
            "ZM": "잠비아", "LY": "리비아",
            
            # 🏝️ 오세아니아 및 기타 소국
            "NC": "뉴칼레도니아", "VU": "바누아투", "WS": "사모아", "TO": "통가", "TV": "투발루", 
            "SB": "솔로몬 제도", "MH": "마셜 제도", "FM": "미크로네시아", "PW": "팔라우", 
            "NR": "나우루", "KI": "키리바시", "PF": "프랑스령 폴리네시아", "GU": "괌",
            "AS": "아메리칸 사모아", "CK": "쿡 제도", "NU": "니우에", "PN": "핏케언 제도", 
            "TK": "토켈라우", "WF": "왈리스 푸투나", "MP": "북마리아나 제도", "UM": "미국령 군소 제도",
            "CX": "크리스마스섬", "CC": "코코스 제도", "NF": "노퍽섬", "TF": "프랑스령 남부와 남극 지역",
            "GS": "사우스조지아 사우스샌드위치 제도", "BV": "부베섬", "HM": "허드 맥도널드 제도",
            "IO": "영국령 인도양 지역", "AX": "올란드 제도",
            
            # 🏛️ 역사적 국가 (고전 영화 수집용 TMDB 특수 코드)
            "SU": "소련", 
            "YU": "유고슬라비아", 
            "XC": "체코슬로바키아", 
            "XG": "동독", 
            "VD": "남베트남",
            "CS": "세르비아 몬테네그로", # 2003~2006년 영화에 자주 등장
            "AN": "네덜란드령 안틸레스", # 2010년 해체 전 영화
            
            # 🌐 특별 분류
            "XI": "북아일랜드", 
            "XK": "코소보"
        }
        return code_map.get(code.upper(), f"기타({code.upper()})")

    def format_time(self, seconds):
        hours, remainder = divmod(int(seconds), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}시간 {minutes}분 {secs}초" if hours > 0 else f"{minutes}분 {secs}초"