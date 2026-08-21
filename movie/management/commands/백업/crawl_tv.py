import gzip
import csv
import requests
import time
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
# 💡 방금 만드신 TV 드라마 전용 모델을 불러옵니다!
from movie.models import TvSeries  
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '월별 방영 시작 드라마(TV) 풀옵션 수집(TMDB) 및 IMDb 로컬 TSV 데이터 결합'

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        # 📅 [설정] 2024년 1월 ~ 12월 전체 수집 리스트
        # (테스트가 필요하시면 2월~12월 앞에 #을 붙여 1월만 먼저 돌려보세요!)
        months = [
            ("2024-01-01", "2024-02-01", "2024년 1월"),
            ("2024-02-01", "2024-03-01", "2024년 2월"),
            ("2024-03-01", "2024-04-01", "2024년 3월"),
            ("2024-04-01", "2024-05-01", "2024년 4월"),
            ("2024-05-01", "2024-06-01", "2024년 5월"),
            ("2024-06-01", "2024-07-01", "2024년 6월"),
            ("2024-07-01", "2024-08-01", "2024년 7월"),
            ("2024-08-01", "2024-09-01", "2024년 8월"),
            ("2024-09-01", "2024-10-01", "2024년 9월"),
            ("2024-10-01", "2024-11-01", "2024년 10월"),
            ("2024-11-01", "2024-12-01", "2024년 11월"),
            ("2024-12-01", "2025-01-01", "2024년 12월"),
            ("2025-01-01", "2025-02-01", "2025년 1월"),
            ("2025-02-01", "2025-03-01", "2025년 2월"),
            ("2025-03-01", "2025-04-01", "2025년 3월"),
            ("2025-04-01", "2025-05-01", "2025년 4월"),
            ("2025-05-01", "2025-06-01", "2025년 5월"),
            ("2025-06-01", "2025-07-01", "2025년 6월"),
            ("2025-07-01", "2025-08-01", "2025년 7월"),
            ("2025-08-01", "2025-09-01", "2025년 8월"),
            ("2025-09-01", "2025-10-01", "2025년 9월"),
            ("2025-10-01", "2025-11-01", "2025년 10월"),
            ("2025-11-01", "2025-12-01", "2025년 11월"),
            ("2025-12-01", "2025-01-01", "2025년 12월"),
            ("2026-01-01", "2026-02-01", "2026년 1월"),
            ("2026-02-01", "2026-03-01", "2026년 2월"),
            ("2026-03-01", "2026-04-01", "2026년 3월"),
            ("2026-04-01", "2026-05-01", "2026년 4월"),
            ("2026-05-01", "2026-06-01", "2026년 5월"),
            ("2026-06-01", "2026-07-01", "2026년 6월"),
            ("2026-07-01", "2026-08-01", "2026년 7월"),
            ("2026-08-01", "2026-09-01", "2026년 8월"),
            ("2026-09-01", "2026-10-01", "2026년 9월"),
            ("2026-10-01", "2026-11-01", "2026년 10월"),
            ("2026-11-01", "2026-12-01", "2026년 11월"),
            ("2026-12-01", "2026-01-01", "2026년 12월"),
        ]

        self.stdout.write(self.style.WARNING("🔥 TMDB + IMDb 드라마(TV) 완전체 크롤러를 가동합니다..."))

        total_months = len(months)
        start_time = time.time()
        created_count = 0

        # 🚀 [속도 극대화 1] 현재 DB에 이미 있는 드라마 ID를 0.1초 만에 메모리로 싹 불러옵니다.
        existing_ids = set(TvSeries.objects.values_list('id', flat=True))
        self.stdout.write(f"📌 현재 DB 보존 드라마: {len(existing_ids)}개 (중복은 API 호출 없이 초고속 스킵합니다!)")

        # ==========================================
        # PHASE 1: TMDB 드라마 풀옵션 데이터 긁어오기
        # ==========================================
        for m_idx, (start, end, label) in enumerate(months, 1):
            self.stdout.write(self.style.NOTICE(f"\n📂 [PHASE 1] [{m_idx}/{total_months}] {label} 방영 시작 드라마 심층 수집 중..."))
            
            end_date_obj = datetime.strptime(end, '%Y-%m-%d') - timedelta(days=1)
            tmdb_end = end_date_obj.strftime('%Y-%m-%d')
            
            page = 1
            # 🚀 [품질 극대화] 월 20페이지(인기순 상위 400개)로 제한! 쓰레기 방송을 거르고 명작만 빠르게 담습니다.
            max_pages = 20
            current_max_pages = max_pages

            while page <= current_max_pages:
                discover_url = f"https://api.themoviedb.org/3/discover/tv?api_key={API_KEY}&language=ko-KR&first_air_date.gte={start}&first_air_date.lte={tmdb_end}&sort_by=popularity.desc&page={page}"
                discover_data = self.fetch_url(discover_url)
                
                if not discover_data or not discover_data.get('results'):
                    break
                
                total_pages_api = discover_data.get('total_pages', 1)
                current_max_pages = min(total_pages_api, max_pages)

                for item in discover_data.get('results', []):
                    tmdb_id = item.get('id')
                    if not tmdb_id: continue

                    # 🚀 [속도 극대화 2] 이미 우리 DB에 수집된 드라마라면 API 요청 안 하고 0.001초 만에 패스!
                    if tmdb_id in existing_ids:
                        continue

                    # 🛡️ [에러 방어막] 불량 데이터나 특수문자 오류를 만나도 스크립트가 뻗지 않도록 감싸줍니다.
                    try:
                        detail_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={API_KEY}&language=ko-KR&append_to_response=credits,videos,watch/providers,recommendations,keywords,content_ratings"
                        data = self.fetch_url(detail_url)
                        if not data: continue

                        # 💡 [핵심 추가] TMDB TV 시리즈는 외부 ID API를 따로 찔러야 IMDb ID(ttXXXXX)를 얻을 수 있습니다!
                        external_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids?api_key={API_KEY}"
                        external_data = self.fetch_url(external_url) or {}
                        imdb_id = (external_data.get('imdb_id', '') or "").strip()

                        title = data.get('name', '')
                        original_title = data.get('original_name', '')
                        poster_path = data.get('poster_path')
                        backdrop_path = data.get('backdrop_path')
                        
                        if not title or not poster_path:
                            continue

                        overview = data.get('overview', '')
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                        tmdb_rating = round(data.get('vote_average', 0.0), 1)
                        vote_count = data.get('vote_count', 0)
                        
                        budget = 0
                        revenue = 0
                        imdb_id = (data.get('imdb_id', '') or "").strip()
                        
                        ep_run_times = data.get('episode_run_time', [])
                        runtime = ep_run_times[0] if ep_run_times else 0

                        release_date_str = data.get('first_air_date', '')
			release_date = None
			if release_date_str:
			    try:
			        # 문자열("2024-01-15")을 파이썬 날짜 객체(date)로 변환
			        release_date = datetime.strptime(release_date_str.strip()[:10], '%Y-%m-%d').date()
			    except (ValueError, TypeError):
			        release_date = None

                        genres = ", ".join([g['name'] for g in data.get('genres', [])])
                        
                        # 1. 인물 정보 (기획자/총괄 프로듀서가 감독 역할)
                        director, director_image_url, screenwriter = "", "", ""
                        creators = data.get('created_by', [])
                        if creators:
                            director = creators[0].get('name', '')
                            director_image_url = f"https://image.tmdb.org/t/p/w185{creators[0].get('profile_path')}" if creators[0].get('profile_path') else ""

                        for crew in data.get('credits', {}).get('crew', []):
                            if not director and crew['job'] in ['Director', 'Executive Producer', 'Series Director']:
                                director = crew['name']
                                director_image_url = f"https://image.tmdb.org/t/p/w185{crew['profile_path']}" if crew.get('profile_path') else ""
                            if crew['job'] in ['Screenplay', 'Writer', 'Writer (Staff)', 'Teleplay'] and not screenwriter:
                                screenwriter = crew['name']
                                
                        cast_list = data.get('credits', {}).get('cast', [])
                        actors = ", ".join([c['name'] for c in cast_list[:5]])
                        actor_details = []
                        for cast in cast_list[:10]:
                            actor_details.append({
                                "name": cast.get('name', ''),
                                "character": cast.get('character', ''),
                                "profile_url": f"https://image.tmdb.org/t/p/w185{cast['profile_path']}" if cast.get('profile_path') else ""
                            })
                            
                        # 2. 예고편
                        trailer_url = ""
                        for video in data.get('videos', {}).get('results', []):
                            if video.get('site') == 'YouTube' and video.get('type') in ['Trailer', 'Teaser']:
                                trailer_url = f"https://www.youtube.com/watch?v={video['key']}"
                                break
                                
                        # 3. OTT 스트리밍
                        streaming_providers = []
                        for prov in data.get('watch/providers', {}).get('results', {}).get('KR', {}).get('flatrate', []):
                            streaming_providers.append({
                                "provider_name": prov.get('provider_name', ''),
                                "logo_url": f"https://image.tmdb.org/t/p/w92{prov.get('logo_path', '')}" if prov.get('logo_path') else ""
                            })
                            
                        # 4. 추천 드라마 & 키워드
                        recommended_movies = []
                        for rec in data.get('recommendations', {}).get('results', [])[:5]:
                            rec_poster = rec.get('poster_path')
                            rec_country = ""
                            if rec.get('origin_country'):
                                rec_country = self.get_country_kr_from_code(rec.get('origin_country')[0])
                            
                            recommended_movies.append({
                                "title": rec.get('name', ''),
                                "poster_url": f"https://image.tmdb.org/t/p/w185{rec_poster}" if rec_poster else "",
                                "release_date": rec.get('first_air_date', '')[:4],
                                "rating": round(rec.get('vote_average', 0.0), 1),
                                "vote_count": rec.get('vote_count', 0), 
                                "country": rec_country,
                                "genre": self.get_genre_kr_from_ids(rec.get('genre_ids', []))
                            })
                        keywords = ", ".join([k['name'] for k in data.get('keywords', {}).get('results', [])])
                        
                        # 5. 관람 등급
                        kr_cert, us_cert = "", ""
                        for cr in data.get('content_ratings', {}).get('results', []):
                            if cr['iso_3166_1'] == 'KR':
                                kr_cert = cr.get('rating', '')
                            elif cr['iso_3166_1'] == 'US':
                                us_cert = cr.get('rating', '')
                                    
                        # 6. 국가 정보
                        prod_code, prod_eng, prod_kr = "", "", ""
                        prod_countries = data.get('production_countries', [])
                        if prod_countries:
                            prod_code = prod_countries[0].get('iso_3166_1', '')
                            prod_eng = prod_countries[0].get('name', '')
                            prod_kr = self.get_country_kr_from_code(prod_code)
                        elif data.get('origin_country'):
                            prod_code = data.get('origin_country')[0]
                            prod_kr = self.get_country_kr_from_code(prod_code)

                        # 안전한 트랜잭션 DB 저장
                        with transaction.atomic():
                            movie, created = TvSeries.objects.update_or_create(
                                id=tmdb_id,
                                defaults={
                                    'tmdb_imdb_id': imdb_id if imdb_id else None,
                                    'tmdb_title': title[:255],
                                    'tmdb_original_title': original_title[:255] if original_title else "",
                                    'tmdb_genre': genres[:255],
                                    'tmdb_release_date': release_date,
                                    'tmdb_runtime': runtime,
                                    'tmdb_rating': tmdb_rating,
                                    'tmdb_vote_count': vote_count,
                                    'tmdb_overview': overview,
                                    'tmdb_poster_url': poster_url,
                                    'backdrop_path': backdrop_path,
                                    'tmdb_trailer_url': trailer_url,
                                    'tmdb_director': director[:255] if director else "",
                                    'tmdb_director_image_url': director_image_url,
                                    'tmdb_screenwriter': screenwriter[:255] if screenwriter else "",
                                    'tmdb_actors': actors[:500] if actors else "",
                                    'tmdb_actor_details': actor_details,
                                    'tmdb_streaming_providers': streaming_providers,
                                    'tmdb_recommended_movies': recommended_movies,
                                    'tmdb_keywords': keywords[:500] if keywords else "",
                                    'tmdb_certification_us': us_cert,
                                    'tmdb_certification_kr': kr_cert,
                                    'tmdb_budget': budget,
                                    'tmdb_revenue': revenue,
                                    'tmdb_production_country_code': prod_code,
                                    'tmdb_production_country_eng': prod_eng,
                                    'tmdb_production_country_kr': prod_kr,
                                }
                            )
                        if created:
                            created_count += 1
                            existing_ids.add(tmdb_id)  # 방금 저장한 ID도 메모리에 추가하여 중복 방지

                    # 🛡️ [에러 방어막 가동] 불량 데이터가 터져도 원인만 출력하고 죽지 않습니다!
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  [건너뜀] ID {tmdb_id} 저장 실패 (원인: {e})"))
                        continue

                # 진행 상황 출력
                elapsed_seconds = time.time() - start_time
                page_progress = (page / current_max_pages) * 100
                avg_time_per_page = elapsed_seconds / (page if page > 0 else 1)
                remaining_pages = current_max_pages - page
                estimated_remaining = avg_time_per_page * remaining_pages
                
                if total_months > 1:
                    remaining_months = total_months - m_idx
                    estimated_remaining += (avg_time_per_page * current_max_pages) * remaining_months
                    
                total_expected_str = self.format_time(elapsed_seconds + estimated_remaining)
                elapsed_str = self.format_time(elapsed_seconds)
                
                status_msg = (
                    f"  ↳ Page {page}/{current_max_pages} 완료 ({page_progress:.1f}%) | "
                    f"경과: {elapsed_str} | 예상: {total_expected_str} "
                    f"(누적 추가: {created_count}개)"
                )
                self.stdout.write(self.style.HTTP_INFO(status_msg))
                page += 1

        # ==========================================
        # PHASE 2: IMDb TSV 파일 파싱 및 매칭
        # ==========================================
        self.stdout.write(self.style.NOTICE(f"\n📁 [PHASE 2] IMDb 로컬 TSV 파일 검증 및 결합 시작..."))

        target_movies = TvSeries.objects.exclude(tmdb_imdb_id__isnull=True).exclude(tmdb_imdb_id='')
        movie_map = {m.tmdb_imdb_id.strip().lower(): m for m in target_movies}
        target_ids = set(movie_map.keys())

        if not target_ids:
            self.stdout.write(self.style.WARNING("매칭할 IMDb ID가 없습니다. 작업을 종료합니다."))
            return

        self.stdout.write(f"🎯 매칭 대상 고유 IMDb ID 개수: {len(target_ids)}개")
        matched_ratings_ids = set()
        matched_basics_ids = set()

        # 1. 평점 파일 읽기
        try:
            self.stdout.write("⏳ [1/2] 'title.ratings.tsv.gz' 일괄 스캔 중...")
            with gzip.open('title.ratings.tsv.gz', 'rt', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        movie = movie_map[tconst_clean]
                        movie.imdb_rating = float(row['averageRating']) if row['averageRating'] != '\\N' else 0.0
                        movie.imdb_vote_count = int(row['numVotes']) if row['numVotes'] != '\\N' else 0
                        matched_ratings_ids.add(tconst_clean)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR("❌ 'title.ratings.tsv.gz' 파일이 프로젝트 폴더에 없습니다!"))

        # 2. 기본 정보 파일 읽기
        try:
            self.stdout.write("⏳ [2/2] 'title.basics.tsv.gz' 일괄 스캔 중...")
            with gzip.open('title.basics.tsv.gz', 'rt', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    tconst_clean = row['tconst'].strip().lower()
                    if tconst_clean in target_ids:
                        movie = movie_map[tconst_clean]
                        
                        rt = row['runtimeMinutes']
                        if rt != '\\N': movie.imdb_runtime = int(rt)
                        
                        g = row['genres']
                        if g != '\\N': movie.imdb_genre = g.replace(',', ', ')
                        
                        year = row['startYear']
                        if year != '\\N': movie.imdb_release_date = year
                        
                        matched_basics_ids.add(tconst_clean)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR("❌ 'title.basics.tsv.gz' 파일이 프로젝트 폴더에 없습니다!"))

        # 벌크 업데이트 수행
        self.stdout.write("⏳ 매칭 완료된 IMDb 데이터 DB 벌크 업데이트 중...")
        with transaction.atomic():
            TvSeries.objects.bulk_update(
                target_movies, 
                ['imdb_rating', 'imdb_vote_count', 'imdb_runtime', 'imdb_genre', 'imdb_release_date'],
                batch_size=500
            )

        self.stdout.write(self.style.SUCCESS(f"\n🎉 모든 작업 완료! 총 {created_count}개의 드라마 데이터가 신규 구축되었습니다."))
        
        unmatched_ids = target_ids - (matched_ratings_ids & matched_basics_ids)
        if unmatched_ids:
            self.stdout.write(self.style.WARNING(f"⚠️ 내 로컬 TSV 파일에 정보가 존재하지 않는 신작 드라마: {len(unmatched_ids)}개"))
        else:
            self.stdout.write(self.style.SUCCESS("✔️ 100% 모든 드라마가 로컬 TSV 파일과 완벽하게 결합되었습니다!"))

    # --- 헬퍼 메서드들 ---
    def fetch_url(self, url):
        while True:
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    return res.json()
                elif res.status_code == 404:
                    return None
                elif res.status_code == 429:
                    self.stdout.write(self.style.WARNING("  [경고] API 제한! 3초 대기..."))
                    time.sleep(3)
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)

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
            
            # 🏝️ 오세아니아 및 기타 소국
            "NC": "뉴칼레도니아", "VU": "바누아투", "WS": "사모아", "TO": "통가", "TV": "투발루", 
            "SB": "솔로몬 제도", "MH": "마셜 제도", "FM": "미크로네시아", "PW": "팔라우", 
            "NR": "나우루", "KI": "키리바시", "PF": "프랑스령 폴리네시아", "GU": "괌",
            "AS": "아메리칸 사모아", "CK": "쿡 제도", "NU": "나우루", "NU": "니우에", "PN": "핏케언 제도", 
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

    def get_genre_kr_from_ids(self, genre_ids):
        if not genre_ids:
            return "정보 없음"
            
        genre_map = {
            28: "액션", 12: "모험", 16: "애니메이션", 35: "코미디", 80: "범죄", 99: "다큐멘터리",
            18: "드라마", 10751: "가족", 14: "판타지", 36: "역사", 27: "공포", 10402: "음악",
            9648: "미스터리", 10749: "로맨스", 878: "SF", 10770: "TV 영화", 53: "스릴러",
            10752: "전쟁", 37: "서부",
            10759: "액션&어드벤처",
            10762: "키즈",
            10763: "뉴스",
            10764: "리얼리티",
            10765: "SF&판타지",
            10766: "소프 오페라(일일드라마)",
            10767: "토크쇼",
            10768: "전쟁&정치"
        }
        genres = [genre_map.get(g_id) for g_id in genre_ids if genre_map.get(g_id)]
        return ", ".join(genres) if genres else "정보 없음"

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}시간 {minutes}분 {secs}초"
        return f"{minutes}분 {secs}초"