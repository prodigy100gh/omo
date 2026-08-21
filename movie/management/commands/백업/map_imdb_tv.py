import gzip
import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from movie.models import TvSeries  

class Command(BaseCommand):
    help = '로컬 IMDb TSV 파일(title.ratings.tsv.gz, title.basics.tsv.gz)을 읽어 TV 시리즈 DB에 초고속 매핑 및 업데이트합니다.'

    def handle(self, *args, **options):
        # =====================================================================
        # [IMDb 로컬 TSV 데이터 결합 전용 로직]
        # =====================================================================
        self.stdout.write(self.style.NOTICE(f"\n📁 IMDb 로컬 TSV 파일 검증 및 결합 전용 스크립트를 시작합니다..."))

        # 1. DB에서 IMDb ID가 존재하는 TV 시리즈만 필터링하여 가져옵니다.
        target_movies = TvSeries.objects.exclude(tmdb_imdb_id__isnull=True).exclude(tmdb_imdb_id='')
        movie_map = {m.tmdb_imdb_id.strip().lower(): m for m in target_movies}
        target_ids = set(movie_map.keys())

        if not target_ids:
            self.stdout.write(self.style.WARNING("매칭할 IMDb ID가 DB에 없습니다. 작업을 종료합니다."))
            return

        self.stdout.write(f"🎯 매칭 대상 고유 IMDb ID 개수: {len(target_ids)}개")
        matched_ratings_ids = set()
        matched_basics_ids = set()

        # 2. 평점 파일(ratings) 스캔 및 매핑
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
            self.stdout.write(self.style.ERROR("❌ 'title.ratings.tsv.gz' 파일이 프로젝트 루트 폴더에 없습니다!"))

        # 3. 기본 정보 파일(basics) 스캔 및 매핑 (러닝타임, 장르, 연도)
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
            self.stdout.write(self.style.ERROR("❌ 'title.basics.tsv.gz' 파일이 프로젝트 루트 폴더에 없습니다!"))

        # 4. 벌크 업데이트 (DB에 한 번에 덮어쓰기하여 속도 최적화)
        self.stdout.write("⏳ 매칭 완료된 IMDb 데이터 DB 벌크 업데이트 중...")
        with transaction.atomic():
            TvSeries.objects.bulk_update(
                target_movies, 
                ['imdb_rating', 'imdb_vote_count', 'imdb_runtime', 'imdb_genre', 'imdb_release_date'],
                batch_size=500
            )

        total_matched = len(matched_ratings_ids | matched_basics_ids)
        self.stdout.write(self.style.SUCCESS(f"\n🎉 모든 작업 완료! 총 {total_matched}개의 드라마에 IMDb 데이터가 결합되었습니다."))