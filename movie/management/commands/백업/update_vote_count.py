import time
import requests
from django.core.management.base import BaseCommand
from movie.models import Movie
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '기존 추천작 데이터에 평가자 수(vote_count)만 초고속으로 추가합니다.'

    def handle(self, *args, **options):
        load_dotenv() # .env 파일 읽기
        API_KEY = os.getenv("TMDB_API_KEY") # 파일에서 키를 안전하게 불러옴
        
        # 💡 [초고속 핵심 1] 추천작이 비어있는 영화는 아예 검색 대상에서 빼버립니다. (시간 대폭 단축)
        movies = Movie.objects.exclude(tmdb_recommended_movies__isnull=True).exclude(tmdb_recommended_movies__exact=[])
        total_movies = movies.count()
        
        self.stdout.write(self.style.WARNING(f"🚀 총 {total_movies}개 영화의 추천작 '평가자 수' 단독 주입을 시작합니다..."))
        
        session = requests.Session() 
        updated_movies = []
        start_time = time.time()
        
        for idx, movie in enumerate(movies, 1):
            url = f"https://api.themoviedb.org/3/movie/{movie.id}/recommendations?api_key={API_KEY}&language=ko-KR"
            
            try:
                res = session.get(url, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    
                    # 💡 API에서 받은 데이터 중 영화 '제목'과 '평가자 수'만 딕셔너리로 뽑아둡니다.
                    # 예: {"인셉션": 23045, "셔터 아일랜드": 15000}
                    vote_map = {}
                    for rec in data.get('results', []):
                        vote_map[rec.get('title')] = rec.get('vote_count', 0)
                        
                    # 기존에 DB에 있던 추천작 데이터를 꺼냅니다.
                    current_recs = movie.tmdb_recommended_movies
                    is_modified = False
                    
                    # 💡 [초고속 핵심 2] 기존 데이터에 vote_count만 쏙쏙 끼워 넣습니다.
                    for my_rec in current_recs:
                        title = my_rec.get('title')
                        if title in vote_map:
                            my_rec['vote_count'] = vote_map[title]
                            is_modified = True
                            
                    # 수정된 내용이 있을 때만 업데이트 리스트에 추가합니다.
                    if is_modified:
                        movie.tmdb_recommended_movies = current_recs
                        updated_movies.append(movie)
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"에러 발생 (ID {movie.id}): {e}"))
                time.sleep(1)
                
            # 100개씩 모아서 DB에 한 방에 덮어씁니다 (Bulk Update)
            if len(updated_movies) >= 100:
                Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
                elapsed_str = self.format_time(time.time() - start_time)
                self.stdout.write(f"  ↳ {idx}/{total_movies} 완료... (진행시간: {elapsed_str})")
                updated_movies.clear() 
                
        # 100개 단위로 묶이지 못하고 남은 자투리 영화들 마저 업데이트
        if updated_movies:
            Movie.objects.bulk_update(updated_movies, ['tmdb_recommended_movies'])
            
        final_time = self.format_time(time.time() - start_time)
        self.stdout.write(self.style.SUCCESS(f"\n🎉 평가자 수 주입 완벽하게 종료! (총 소요시간: {final_time})"))

    def format_time(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}분 {secs}초"