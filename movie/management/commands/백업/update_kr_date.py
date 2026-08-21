import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.utils import timezone
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from movie.models import Movie

class Command(BaseCommand):
    help = '멀티스레딩, 세션 풀링을 이용해 개봉일을 채우고, TMDB에서 삭제된 유령 영화는 로컬 DB에서도 자동 삭제 후 목록을 출력합니다.'

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        if not API_KEY:
            self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY가 설정되지 않았습니다."))
            return

        target_movies = list(Movie.objects.filter(tmdb_release_date_kr__isnull=True))
        total_count = len(target_movies)

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("🎉 모든 영화의 개봉일 작업이 완료되어 있습니다!"))
            return

        self.stdout.write(self.style.WARNING(f"🚀 [자동 삭제 및 리스트 출력 탑재] 하이퍼 스피드 업데이트 시작! (대상: {total_count}개)"))

        session = requests.Session()
        retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries))

        updated_movies = []
        deleted_movies_info = []  # 💡 🗑️ 삭제할 영화 정보(ID, 제목)를 함께 담아둘 바구니
        
        success_count = 0
        batch_size = 500  
        max_workers = 40  

        def fetch_release_date(movie):
            url = f"https://api.themoviedb.org/3/movie/{movie.id}/release_dates?api_key={API_KEY}"
            try:
                res = session.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    kr_date = None
                    for rd in data.get('results', []):
                        if rd['iso_3166_1'] == 'KR':
                            raw_date = next((r['release_date'] for r in rd['release_dates'] if r.get('release_date')), "")
                            if raw_date:
                                kr_date = raw_date[:10]
                            break
                    return movie, kr_date, 200
                elif res.status_code == 404:
                    return movie, None, 404
                else:
                    return movie, None, res.status_code
            except Exception as e:
                return movie, None, str(e)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_movie = {executor.submit(fetch_release_date, movie): movie for movie in target_movies}
            
            for i, future in enumerate(as_completed(future_to_movie), 1):
                movie, kr_date, status = future.result()
                
                if status == 200:
                    if kr_date:
                        movie.tmdb_release_date_kr = kr_date
                        movie.updated_at = timezone.now()
                        updated_movies.append(movie)
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(f"  ↳ [{i}/{total_count}] ✅ {movie.tmdb_title} ➔ {kr_date}"))
                elif status == 404:
                    # 💡 404 에러 시 ID뿐만 아니라 제목도 튜플 형태로 함께 기억해 둡니다.
                    deleted_movies_info.append((movie.id, movie.tmdb_title))
                    self.stdout.write(self.style.ERROR(f"  ↳ [{i}/{total_count}] 🗑️ {movie.tmdb_title} (ID: {movie.id}) ➔ TMDB 삭제 감지됨 (로컬 DB 자동 삭제 대기)"))
                else:
                    self.stdout.write(self.style.ERROR(f"  ↳ [{i}/{total_count}] ❌ {movie.tmdb_title} ➔ 통신 에러 ({status})"))

                if len(updated_movies) >= batch_size:
                    Movie.objects.bulk_update(updated_movies, ['tmdb_release_date_kr', 'updated_at'])
                    updated_movies.clear()

        if updated_movies:
            Movie.objects.bulk_update(updated_movies, ['tmdb_release_date_kr', 'updated_at'])

        # 🚀 [업그레이드된 최종 청소 및 리스트 출력 로직]
        if deleted_movies_info:
            # 기억해 둔 정보에서 ID만 쏙쏙 뽑아내어 한 방에 삭제 쿼리 전송
            deleted_ids = [info[0] for info in deleted_movies_info]
            deleted_count, _ = Movie.objects.filter(id__in=deleted_ids).delete()
            
            self.stdout.write(self.style.WARNING(f"\n🧹 유령 데이터 청소 완료: 총 {deleted_count}개의 영화가 DB에서 영구 삭제되었습니다."))
            
            # 마지막에 보기 좋게 삭제된 리스트 출력!
            self.stdout.write(self.style.WARNING("-" * 50))
            self.stdout.write(self.style.WARNING("🚨 [삭제된 영화 목록]"))
            for m_id, m_title in deleted_movies_info:
                self.stdout.write(self.style.WARNING(f"  - {m_title} (ID: {m_id})"))
            self.stdout.write(self.style.WARNING("-" * 50))

        self.stdout.write(self.style.SUCCESS(f"\n✨ 하이퍼 스피드 작업 완료! 총 {success_count}개의 영화에 한국 개봉일이 성공적으로 추가되었습니다."))