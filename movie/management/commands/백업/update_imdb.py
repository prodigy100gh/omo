import gzip
import csv
import time
from django.core.management.base import BaseCommand
from django.db import transaction
from movie.models import Movie  # 💡 앱 이름에 맞게 수정하세요 (movie)

class Command(BaseCommand):
    help = 'IMDb 로컬 TSV 데이터를 읽어 기존 영화 DB에 매핑 및 업데이트 (안전한 분할 저장)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("🔥 [IMDb 전용 매핑 툴] TSV 데이터 결합을 시작합니다..."))
        start_time = time.time()

        # 1. 매핑할 대상 영화 불러오기 (IMDb ID가 있는 영화들)
        target_movies = Movie.objects.exclude(tmdb_imdb_id__isnull=True).exclude(tmdb_imdb_id='')
        
        # 리스트를 딕셔너리로 만들어 매칭 속도를 극대화
        movie_map = {m.tmdb_imdb_id.strip().lower(): m for m in target_movies}
        target_ids = set(movie_map.keys())

        if not target_ids:
            self.stdout.write(self.style.WARNING("❌ 매칭할 IMDb ID가 데이터베이스에 없습니다. 작업을 종료합니다."))
            return

        self.stdout.write(self.style.HTTP_INFO(f"🎯 매칭 대상 고유 IMDb ID 개수: {len(target_ids)}개"))
        
        matched_ratings_ids = set()
        matched_basics_ids = set()

        # ==========================================
        # 단계 1: 평점 및 평가자 수 매핑
        # ==========================================
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
            self.stdout.write(self.style.ERROR("❌ 'title.ratings.tsv.gz' 파일이 프로젝트 최상단 폴더에 없습니다!"))
            return

        # ==========================================
        # 단계 2: 장르, 러닝타임, 개봉년도 매핑
        # ==========================================
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
            self.stdout.write(self.style.ERROR("❌ 'title.basics.tsv.gz' 파일이 프로젝트 최상단 폴더에 없습니다!"))
            return

        # ==========================================
        # 단계 3: 🌟 데이터베이스 안전 업데이트 (Batch 처리)
        # ==========================================
        self.stdout.write(self.style.NOTICE("⏳ 매칭 완료된 데이터를 DB에 '500개씩 안전하게' 나누어 업데이트 중..."))
        
        # 메모리에 업데이트된 객체 리스트 준비
        movies_to_update = list(movie_map.values())
        
        with transaction.atomic():
            # 💡 핵심 해결책: batch_size=500 을 추가하여 SQLite 변수 초과 에러 방지!
            Movie.objects.bulk_update(
                movies_to_update, 
                ['imdb_rating', 'imdb_vote_count', 'imdb_runtime', 'imdb_genre', 'imdb_release_date'],
                batch_size=500 
            )

        # 결과 리포트
        elapsed_seconds = time.time() - start_time
        mins = int(elapsed_seconds // 60)
        secs = int(elapsed_seconds % 60)
        
        self.stdout.write(self.style.SUCCESS(f"\n🎉 작업 완료! ({mins}분 {secs}초 소요)"))
        
        unmatched_ids = target_ids - (matched_ratings_ids & matched_basics_ids)
        if unmatched_ids:
            self.stdout.write(self.style.WARNING(f"⚠️ 내 로컬 TSV 파일에 정보가 없는 최신/마이너 영화: {len(unmatched_ids)}개"))
        else:
            self.stdout.write(self.style.SUCCESS("✔️ 100% 모든 영화가 로컬 TSV 파일과 완벽하게 결합되었습니다!"))