import gzip
import csv
import requests
import time
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from movie.models import Movie, TvSeries
import os
from dotenv import load_dotenv

# 💡 [초보자 안내] BaseCommand를 상속받으면 터미널에서 'python manage.py 명령어이름' 으로 실행할 수 있는 나만의 커스텀 스크립트가 됩니다.
class Command(BaseCommand):
    help = '영화 및 TV 시리즈 풀옵션 통합 수집 (완전판: 220개국 국가/장르 완벽 번역 포함)'

    # =====================================================================
    # 💡 [명령어 옵션 설정] 터미널에서 입력받을 옵션들을 정의합니다.
    # =====================================================================
    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='수집 시작 전 DB를 완전히 삭제(초기화)합니다.')
        parser.add_argument('--target', type=str, default='all', choices=['all', 'movie', 'tv'], help='수집할 대상을 선택합니다')

    # 💡 [메인 함수] 명령어를 실행했을 때 가장 먼저 작동하는 진입점입니다.
    def handle(self, *args, **options):
        # 🔑 본인의 TMDB API Key 불러오기
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")
        target = options['target']

        # 🚨 [DB 초기화 옵션] --clear 옵션을 주었을 때만 작동합니다.
        if options['clear']:
            self.stdout.write(self.style.ERROR(f"⚠️ 경고: '{target}' 대상 DB를 완전히 삭제합니다..."))
            if target in ['all', 'movie']: Movie.objects.all().delete()
            if target in ['all', 'tv']: TvSeries.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("✅ DB 초기화 완료! 깨끗한 상태에서 수집을 시작합니다.\n"))

        # 📅 [수집 기간 설정] 언제부터 언제까지의 데이터를 긁어올지 설정합니다.
        START_DATE = "2025-01-01"  # 수집 시작일 (이상)
        END_DATE = "2026-08-01"    # 수집 종료일 (미만)

        start_dt = datetime.strptime(START_DATE, "%Y-%m-%d")
        end_dt = datetime.strptime(END_DATE, "%Y-%m-%d")

        months = []
        current_dt = start_dt

        # 💡 시작일부터 종료일 전까지 1개월 단위로 쪼개서 리스트(months)를 자동 생성합니다.
        while current_dt < end_dt:
            if current_dt.month == 12: next_dt = current_dt.replace(year=current_dt.year + 1, month=1)
            else: next_dt = current_dt.replace(month=current_dt.month + 1)
            label = f"{current_dt.year}년 {current_dt.month}월"
            months.append((current_dt.strftime("%Y-%m-%d"), next_dt.strftime("%Y-%m-%d"), label))
            current_dt = next_dt

        self.stdout.write(self.style.WARNING(f"🔥 무적의 통합 크롤러 가동 ({START_DATE} ~ {END_DATE} 전까지, 타겟: {target.upper()})..."))

        # 🚀 선택한 타겟에 따라 크롤링 함수를 호출합니다.
        if target in ['all', 'movie']: self.crawl_movies(months, API_KEY)
        if target in ['all', 'tv']: self.crawl_tv(months, API_KEY)

        self.stdout.write(self.style.SUCCESS(f"\n🎉 [{target.upper()}] 대상의 모든 크롤링 작업이 완벽하게 종료되었습니다!"))

    # =====================================================================
    # 🎬 [영화 크롤링 제어 타워]
    # =====================================================================
    def crawl_movies(self, months, API_KEY):
        total_months = len(months)
        start_time = time.time()
        created_count, updated_count, global_pages_processed = 0, 0, 0
        total_errors = [] 

        # 💡 [속도 극대화] 이미 DB에 있는 영화 ID들을 미리 가져와 중복 수집을 초고속으로 스킵합니다.
        existing_ids = set(Movie.objects.values_list('id', flat=True))
        self.stdout.write(self.style.WARNING(f"\n[영화 수집 시작] 📌 현재 DB 보존 영화: {len(existing_ids)}개 (중복 스킵)"))

        # 💡 설정한 개월 수만큼 반복하면서 TMDB API에 데이터를 요청합니다.
        for m_idx, (start, end, label) in enumerate(months, 1):
            self.stdout.write(self.style.NOTICE(f"\n📂 [MOVIE PHASE 1] [{m_idx}/{total_months}] {label} 개봉 영화 수집 중..."))
            tmdb_end = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            page = 1
            current_max_pages = 500
            phase_errors = [] 

            # 💡 TMDB는 한 번에 20개씩만 주므로, 페이지를 넘기며 긁어옵니다.
            while page <= current_max_pages:
                # 💡 [검색 조건] primary_release_date로 해당 월의 한국(KR) 개봉작을 인기순으로 긁어옵니다.  &region=KR 삭제함
                discover_url = f"https://api.themoviedb.org/3/discover/movie?api_key={API_KEY}&language=ko-KR&primary_release_date.gte={start}&primary_release_date.lte={tmdb_end}&sort_by=popularity.desc&page={page}"
                discover_data = self.fetch_url(discover_url)
                
                if not discover_data or not discover_data.get('results'): break 
                current_max_pages = min(discover_data.get('total_pages', 1), 500)
                page_errors = []

                # 💡 목록에서 영화를 하나씩 꺼내 상세 정보를 요청하고 DB에 저장합니다.
                for item in discover_data.get('results', []):
                    tmdb_id = item.get('id')
                    if not tmdb_id: continue
                    status = self._fetch_and_save_movie(tmdb_id, API_KEY, existing_ids)
                    if status == "CREATED": created_count += 1
                    elif status == "UPDATED": updated_count += 1
                    elif status == "ERROR": page_errors.append(tmdb_id)

                # 🚀 [1차 재시도] 에러가 난 항목들은 페이지가 끝날 때 1차로 다시 시도합니다.
                if page_errors:
                    time.sleep(1) 
                    still_errors = []
                    for tmdb_id in page_errors:
                        status = self._fetch_and_save_movie(tmdb_id, API_KEY, existing_ids)
                        if status == "CREATED": created_count += 1
                        elif status == "UPDATED": updated_count += 1
                        elif status == "ERROR": still_errors.append(tmdb_id)
                    phase_errors.extend(still_errors) 

                # ⏱️ 진행률 및 예상 남은 시간을 계산하여 화면에 보여줍니다.
                global_pages_processed += 1
                elapsed_seconds = time.time() - start_time
                avg_time_per_page = elapsed_seconds / global_pages_processed
                remaining_pages_in_phase = current_max_pages - page
                total_remaining_pages = remaining_pages_in_phase + ((total_months - m_idx) * current_max_pages)
                
                status_msg = (f"  ↳ Page {page}/{current_max_pages} 완료 | "
                              f"전체경과: {self.format_time(elapsed_seconds)} | 남은시간: {self.format_time(total_remaining_pages * avg_time_per_page)} "
                              f"(추가: {created_count} 갱신: {updated_count})")
                self.stdout.write(self.style.HTTP_INFO(status_msg))
                page += 1

            # 🚀 [2차 재시도] 페이즈(월)가 끝날 때 남은 에러들을 마지막으로 다시 시도합니다.
            if phase_errors:
                time.sleep(2)
                for tmdb_id in phase_errors:
                    status = self._fetch_and_save_movie(tmdb_id, API_KEY, existing_ids)
                    if status == "CREATED": created_count += 1
                    elif status == "UPDATED": updated_count += 1
                    elif status == "ERROR": total_errors.append(tmdb_id)

        # 📁 [PHASE 2] TMDB 수집이 끝나면 로컬에 있는 IMDb 파일과 결합합니다.
        self._match_imdb_data(Movie)
        
        if total_errors:
            self.stdout.write(self.style.ERROR(f"\n❌ [영화 최종 실패] {len(total_errors)}건: {total_errors}"))
        else:
            self.stdout.write(self.style.SUCCESS("\n✨ [영화] 단 1건의 에러도 없이 완벽하게 수집되었습니다!"))

    # =====================================================================
    # 📺 [TV 시리즈 크롤링 제어 타워]
    # =====================================================================
    def crawl_tv(self, months, API_KEY):
        total_months = len(months)
        start_time = time.time()
        created_count, updated_count, global_pages_processed = 0, 0, 0
        total_errors = [] 

        # 💡 시즌 데이터까지 완벽하게 업데이트된 TV 시리즈 ID만 뽑아서 스킵 명단을 만듭니다.
        fully_updated_ids = set(TvSeries.objects.exclude(seasons_data__isnull=True).exclude(seasons_data=[]).values_list('id', flat=True))
        self.stdout.write(self.style.WARNING(f"\n[TV 수집 시작] 📌 완벽한 데이터 보존 시리즈: {len(fully_updated_ids)}개 (스킵)"))

        for m_idx, (start, end, label) in enumerate(months, 1):
            self.stdout.write(self.style.NOTICE(f"\n📂 [TV PHASE 1] [{m_idx}/{total_months}] {label} 방영 드라마 수집 중..."))
            tmdb_end = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            page = 1
            # 💡 [핵심] 쓰레기 데이터를 피하면서 글로벌 신작을 놓치지 않기 위해 100페이지(2000개)로 넉넉히 설정!
            current_max_pages = 100 
            phase_errors = [] 

            while page <= current_max_pages:
                # 💡 [검색 조건] 'first_air_date'를 사용하여 해당 월에 "첫 방영(초연)"을 시작한 진짜 신작만 가져옵니다!
                discover_url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=ko-KR&first_air_date.gte={start}&first_air_date.lte={tmdb_end}&sort_by=popularity.desc&page={page}"
                discover_data = self.fetch_url(discover_url)
                
                if not discover_data or not discover_data.get('results'): break
                
                # 💡 마찬가지로 상한선을 100페이지로 잡아줍니다.
                current_max_pages = min(discover_data.get('total_pages', 1), 100)
                page_errors = []

                for item in discover_data.get('results', []):
                    tmdb_id = item.get('id')
                    if not tmdb_id: continue
                    status = self._fetch_and_save_tv(tmdb_id, API_KEY, fully_updated_ids)
                    if status == "CREATED": created_count += 1
                    elif status == "UPDATED": updated_count += 1
                    elif status == "ERROR": page_errors.append(tmdb_id)

                # 🚀 [1차 재시도] 페이지 단위 에러 복구
                if page_errors:
                    time.sleep(1)
                    still_errors = []
                    for tmdb_id in page_errors:
                        status = self._fetch_and_save_tv(tmdb_id, API_KEY, fully_updated_ids)
                        if status == "CREATED": created_count += 1
                        elif status == "UPDATED": updated_count += 1
                        elif status == "ERROR": still_errors.append(tmdb_id)
                    phase_errors.extend(still_errors) 

                global_pages_processed += 1
                elapsed_seconds = time.time() - start_time
                avg_time_per_page = elapsed_seconds / global_pages_processed
                remaining_pages_in_phase = current_max_pages - page
                total_remaining_pages = remaining_pages_in_phase + ((total_months - m_idx) * current_max_pages)
                
                status_msg = (f"  ↳ Page {page}/{current_max_pages} 완료 | "
                              f"전체경과: {self.format_time(elapsed_seconds)} | 남은시간: {self.format_time(total_remaining_pages * avg_time_per_page)} "
                              f"(추가: {created_count} 갱신: {updated_count})")
                self.stdout.write(self.style.HTTP_INFO(status_msg))
                page += 1

            # 🚀 [2차 재시도] 페이즈 단위 에러 최종 복구
            if phase_errors:
                time.sleep(2)
                for tmdb_id in phase_errors:
                    status = self._fetch_and_save_tv(tmdb_id, API_KEY, fully_updated_ids)
                    if status == "CREATED": created_count += 1
                    elif status == "UPDATED": updated_count += 1
                    elif status == "ERROR": total_errors.append(tmdb_id)

        # 📁 [PHASE 2] TV 시리즈도 IMDb 파일과 결합합니다.
        self._match_imdb_data(TvSeries)

        if total_errors:
            self.stdout.write(self.style.ERROR(f"\n❌ [TV 최종 실패] {len(total_errors)}건: {total_errors}"))
        else:
            self.stdout.write(self.style.SUCCESS("\n✨ [TV] 단 1건의 에러도 없이 완벽하게 수집되었습니다!"))

    # =====================================================================
    # ⚙️ [영화 상세 정보 수집 로직]
    # =====================================================================
    def _fetch_and_save_movie(self, tmdb_id, API_KEY, existing_ids):
        # 💡 [속도 최적화] 이미 우리 DB에 있는 영화라면 API 통신 없이 초고속 스킵!
        if tmdb_id in existing_ids: return "SKIP"
        try:
            # 💡 [API 호출] 배우, 영상, 플랫폼, 추천작, 키워드 등을 한 방에 요청합니다.
            detail_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={API_KEY}&language=ko-KR&append_to_response=credits,videos,watch/providers,recommendations,keywords,release_dates"
            data = self.fetch_url(detail_url)
            if not data: return "ERROR"

            title, original_title, poster_path = data.get('title', ''), data.get('original_title', ''), data.get('poster_path')
            if not title or not poster_path: return "SKIP"  # 제목이나 포스터가 없는 껍데기 데이터 방어

            # 💡 감독, 각본가 정보 추출
            director, director_id, director_image_url = "", None, ""
            screenwriter, screenwriter_id = "", None
            for crew in data.get('credits', {}).get('crew', []):
                if crew['job'] == 'Director' and not director:
                    director, director_id, director_image_url = crew['name'], crew.get('id'), f"https://image.tmdb.org/t/p/w185{crew['profile_path']}" if crew.get('profile_path') else ""
                if crew['job'] in ['Screenplay', 'Writer'] and not screenwriter:
                    screenwriter, screenwriter_id = crew['name'], crew.get('id')
                    
            # 💡 배우 정보 (이름 문자열 5명, 상세 정보 리스트 10명 추출)
            cast_list = data.get('credits', {}).get('cast', [])
            actors = ", ".join([c['name'] for c in cast_list[:5]])
            actor_details = [{"id": c.get('id'), "name": c.get('name', ''), "character": c.get('character', ''), "profile_url": f"https://image.tmdb.org/t/p/w185{c['profile_path']}" if c.get('profile_path') else ""} for c in cast_list[:10]]
            
            # 💡 유튜브 트레일러 주소 및 스트리밍 OTT 로고/이름 추출
            trailer_url = next((f"https://www.youtube.com/watch?v={v['key']}" for v in data.get('videos', {}).get('results', []) if v.get('site') == 'YouTube' and v.get('type') in ['Trailer', 'Teaser']), "")
            streaming_providers = [{"provider_name": p.get('provider_name', ''), "logo_url": f"https://image.tmdb.org/t/p/w92{p.get('logo_path', '')}" if p.get('logo_path') else ""} for p in data.get('watch/providers', {}).get('results', {}).get('KR', {}).get('flatrate', [])]
                
            # 💡 연관 추천 영화 5개 추출 (고유 ID 포함)
            recommended_movies = []
            for rec in data.get('recommendations', {}).get('results', [])[:5]:
                rec_country = self.get_country_kr_from_code(rec.get('origin_country')[0]) if rec.get('origin_country') else ""
                recommended_movies.append({
                    "id": rec.get('id'), "title": rec.get('title', ''), "poster_url": f"https://image.tmdb.org/t/p/w185{rec.get('poster_path')}" if rec.get('poster_path') else "",
                    "release_date": rec.get('release_date', '')[:4], "rating": round(rec.get('vote_average', 0.0), 1),
                    "vote_count": rec.get('vote_count', 0), "country": rec_country, "genre": self.get_genre_kr_from_ids(rec.get('genre_ids', []))
                })
            
            # 💡 한/미 관람 등급 추출
            kr_cert, us_cert = "", ""
            kr_release_date = None  # 💡 한국 개봉일 초기화

            for rd in data.get('release_dates', {}).get('results', []):
                if rd['iso_3166_1'] == 'KR': 
                    kr_cert = next((r['certification'] for r in rd['release_dates'] if r.get('certification')), "")
                    # 💡 한국 개봉일 추출 (TMDB가 주는 "2024-02-28T00:00:00.000Z" 형태에서 날짜만 싹둑 자르기)
                    raw_kr_date = next((r['release_date'] for r in rd['release_dates'] if r.get('release_date')), "")
                    if raw_kr_date:
                        kr_release_date = raw_kr_date[:10]  # "YYYY-MM-DD" 형태로 자름
                        
                elif rd['iso_3166_1'] == 'US': 
                    us_cert = next((r['certification'] for r in rd['release_dates'] if r.get('certification')), "")
                    
            # 💡 제작 국가 추출
            prod_code, prod_eng, prod_kr = "", "", ""
            if data.get('production_countries'):
                prod_code, prod_eng = data.get('production_countries')[0].get('iso_3166_1', ''), data.get('production_countries')[0].get('name', '')
                prod_kr = self.get_country_kr_from_code(prod_code)

            # 💡 [핵심] TMDB 장르도 무조건 영어->한글 번역기를 통과시킴
            raw_genres = ", ".join([g['name'] for g in data.get('genres', [])])
            korean_genres = self.translate_text_genres(raw_genres)

            # 💡 DB 저장 (에러 시 안전하게 롤백되는 transaction.atomic 사용)
            with transaction.atomic():
                movie, created = Movie.objects.update_or_create(
                    id=tmdb_id,
                    defaults={
                        'tmdb_imdb_id': (data.get('imdb_id', '') or "").strip() or None,
                        'tmdb_title': title, 'tmdb_original_title': original_title,
                        'tmdb_genre': korean_genres, # 💡 번역된 장르 삽입
                        'tmdb_release_date': data.get('release_date') or None, 'tmdb_runtime': data.get('runtime', 0),
                        'tmdb_release_date_kr': data.get('release_date') or None, 'tmdb_runtime': data.get('runtime', 0),
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
                )
            existing_ids.add(tmdb_id)
            return "CREATED" if created else "UPDATED"
        except Exception as e:
            return "ERROR"

    # =====================================================================
    # ⚙️ [TV 시리즈 상세 정보 수집 로직]
    # =====================================================================
    def _fetch_and_save_tv(self, tmdb_id, API_KEY, fully_updated_ids):
        if tmdb_id in fully_updated_ids: return "SKIP"
        try:
            detail_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={API_KEY}&language=ko-KR&append_to_response=credits,videos,watch/providers,recommendations,keywords,content_ratings"
            data = self.fetch_url(detail_url)
            if not data: return "ERROR"

            title, poster_path = data.get('name', ''), data.get('poster_path')
            if not title or not poster_path: return "SKIP"

            # 💡 시즌별 회차, 방영일, 평점, 투표수(vote_count) 정보 추출 (스페셜 시즌인 0은 제외)
            seasons_data = [{'season_number': s.get('season_number'), 'name': s.get('name', ''), 'air_date': s.get('air_date', ''), 'episode_count': s.get('episode_count', 0), 'poster_path': s.get('poster_path', ''), 'vote_average': round(s.get('vote_average', 0.0), 1), 'vote_count': s.get('vote_count', 0)} for s in data.get('seasons', []) if s.get('season_number') != 0]

            # 💡 제작자 및 크루 명단에서 감독, 각본가 색출
            director, director_id, director_image_url = "", None, ""
            screenwriter, screenwriter_id = "", None
            if data.get('created_by'):
                director, director_id, director_image_url = data.get('created_by')[0].get('name', ''), data.get('created_by')[0].get('id'), f"https://image.tmdb.org/t/p/w185{data.get('created_by')[0].get('profile_path')}" if data.get('created_by')[0].get('profile_path') else ""

            for crew in data.get('credits', {}).get('crew', []):
                if not director and crew['job'] in ['Director', 'Executive Producer', 'Series Director']:
                    director, director_id, director_image_url = crew['name'], crew.get('id'), f"https://image.tmdb.org/t/p/w185{crew['profile_path']}" if crew.get('profile_path') else ""
                if crew['job'] in ['Screenplay', 'Writer', 'Writer (Staff)', 'Teleplay'] and not screenwriter:
                    screenwriter, screenwriter_id = crew['name'], crew.get('id')
                    
            # 💡 TV 출연진 리스트 정리
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
                        
            prod_code, prod_eng, prod_kr = "", "", ""
            if data.get('production_countries'):
                prod_code, prod_eng = data.get('production_countries')[0].get('iso_3166_1', ''), data.get('production_countries')[0].get('name', '')
                prod_kr = self.get_country_kr_from_code(prod_code)
            elif data.get('origin_country'):
                prod_code = data.get('origin_country')[0]
                prod_kr = self.get_country_kr_from_code(prod_code)

            # 💡 [핵심] TMDB 장르도 무조건 영어->한글 번역기를 통과시킴
            raw_genres = ", ".join([g['name'] for g in data.get('genres', [])])
            korean_genres = self.translate_text_genres(raw_genres)

            # 💡 외부 아이디(IMDb ID) 호출 및 러닝타임 추출
            external_id_res = self.fetch_url(f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids?api_key={API_KEY}") or {}
            imdb_id = (external_id_res.get('imdb_id', '') or "").strip()
            ep_run_times = data.get('episode_run_time', [])

            # 💡 DB 저장
            with transaction.atomic():
                series, created = TvSeries.objects.update_or_create(
                    id=tmdb_id,
                    defaults={
                        'tmdb_imdb_id': imdb_id if imdb_id else None,
                        'tmdb_title': title[:255], 'tmdb_original_title': data.get('original_name', '')[:255],
                        'tmdb_genre': korean_genres[:255], # 💡 번역된 장르 삽입
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
                        'tmdb_budget': 0,
                        'tmdb_revenue': 0,
                    }
                )
            fully_updated_ids.add(tmdb_id)
            return "CREATED" if created else "UPDATED"
        except Exception as e:
            return "ERROR"

    # =====================================================================
    # 🔗 [공통 로컬 IMDb TSV 파싱 및 결합]
    # =====================================================================
    def _match_imdb_data(self, model_class):
        model_name = "영화" if model_class == Movie else "TV 시리즈"
        self.stdout.write(self.style.NOTICE(f"\n📁 [PHASE 2] {model_name} IMDb 로컬 TSV 데이터 결합 시작..."))

        # 💡 DB에서 IMDb ID가 존재하는 작품만 솎아내서 딕셔너리로 묶어둡니다 (매칭 속도 극대화).
        target_items = model_class.objects.exclude(tmdb_imdb_id__isnull=True).exclude(tmdb_imdb_id='')
        item_map = {m.tmdb_imdb_id.strip().lower(): m for m in target_items}
        target_ids = set(item_map.keys())

        if not target_ids: return

        self.stdout.write(f"🎯 매칭 대상 고유 IMDb ID 개수: {len(target_ids)}개")

        # 💡 평점 파일(ratings) 스캔 및 메모리에서 업데이트
        try:
            self.stdout.write("⏳ [1/2] 'title.ratings.tsv.gz' 스캔 중...")
            with gzip.open('title.ratings.tsv.gz', 'rt', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        obj = item_map[tconst_clean]
                        obj.imdb_rating = float(row['averageRating']) if row['averageRating'] != '\\N' else 0.0
                        obj.imdb_vote_count = int(row['numVotes']) if row['numVotes'] != '\\N' else 0
        except FileNotFoundError: self.stdout.write(self.style.ERROR("❌ 'title.ratings.tsv.gz' 없음!"))

        # 💡 기본 정보 파일(basics) 스캔 및 메모리에서 업데이트 (러닝타임, 장르, 연도)
        try:
            self.stdout.write("⏳ [2/2] 'title.basics.tsv.gz' 스캔 중...")
            with gzip.open('title.basics.tsv.gz', 'rt', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        obj = item_map[tconst_clean]
                        rt, g, year = row['runtimeMinutes'], row['genres'], row['startYear']
                        if rt != '\\N': obj.imdb_runtime = int(rt)
                        # 💡 [핵심] IMDb 영어 장르를 강제로 한글로 싹 바꿔서 넣습니다!
                        if g != '\\N': obj.imdb_genre = self.translate_text_genres(g)
                        if year != '\\N': obj.imdb_release_date = year
        except FileNotFoundError: self.stdout.write(self.style.ERROR("❌ 'title.basics.tsv.gz' 없음!"))

        # 💡 [벌크 업데이트] 메모리에서 수정한 정보들을 500개씩 묶어서 DB에 한 번에 덮어씁니다.
        self.stdout.write("⏳ 매칭 완료된 IMDb 데이터 DB 벌크 업데이트 중...")
        with transaction.atomic():
            model_class.objects.bulk_update(
                target_items, ['imdb_rating', 'imdb_vote_count', 'imdb_runtime', 'imdb_genre', 'imdb_release_date'], batch_size=500
            )

    # =====================================================================
    # 🛠️ [헬퍼 메서드 모음]
    # =====================================================================
    def fetch_url(self, url):
        """외부 통신 중 에러가 나거나 제한(429)이 걸려도 튕기지 않게 재시도해주는 보호막 함수입니다."""
        while True:
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200: return res.json()
                elif res.status_code == 404: return None
                elif res.status_code == 429: time.sleep(3)
                else: time.sleep(2)
            except Exception: time.sleep(2)

    # 💡 1. 영어 장르(문자열) ➔ 한글 번역기 (IMDb & TMDB 방어용)
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
            "Action & Adventure": "액션&어드벤처", "Sci-Fi & Fantasy": "SF&판타지",
            "War & Politics": "전쟁&정치", "Kids": "가족", "Soap": "소프 오페라",
            "Reality": "리얼리티", "Talk": "토크쇼"
        }
        translated = [mapping.get(g.strip(), g.strip()) for g in genre_str.replace('/', ',').split(',') if g.strip()]
        return ", ".join(translated)

    # 💡 2. 숫자 ID 장르 ➔ 한글 번역기 (추천작 전용)
    def get_genre_kr_from_ids(self, genre_ids):
        if not genre_ids: return "정보 없음"
        genre_map = {
            28: "액션", 12: "모험", 16: "애니메이션", 35: "코미디", 80: "범죄", 99: "다큐멘터리",
            18: "드라마", 10751: "가족", 14: "판타지", 36: "역사", 27: "공포", 10402: "음악",
            9648: "미스터리", 10749: "로맨스", 878: "SF", 10770: "TV 영화", 53: "스릴러",
            10752: "전쟁", 37: "서부", 10759: "액션&어드벤처", 10762: "키즈", 10763: "뉴스",
            10764: "리얼리티", 10765: "SF&판타지", 10766: "소프 오페라", 10767: "토크쇼", 10768: "전쟁&정치"
        }
        genres = [genre_map.get(g_id) for g_id in genre_ids if genre_map.get(g_id)]
        return ", ".join(genres) if genres else "정보 없음"

    # 💡 3. 전 세계 220개국 완벽 매핑 사전 (이모지 및 대륙별 구역 완벽 복구)
    def get_country_kr_from_code(self, code):
        """전 세계 국가 코드를 한글로 완벽 매핑하는 종결 버전 (약 220개국 + 역사적 국가)"""
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

    # 💡 초 단위 시간을 'X시간 Y분 Z초' 형태로 예쁘게 변환해 줍니다.
    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0: return f"{hours}시간 {minutes}분 {secs}초"
        return f"{minutes}분 {secs}초"