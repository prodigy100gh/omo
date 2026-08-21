import requests
import time
from django.core.management.base import BaseCommand
from django.db.models import Q
from movie.models import Movie  # 앱 이름(movie)에 맞춰 수정하세요
import os
from dotenv import load_dotenv

# 💡 [초보자 안내] 기존 영화 DB에서 'backdrop_path(가로 배경 이미지)'가 비어있는 녀석들만 찾아서 채워주는 전용 스크립트입니다.
class Command(BaseCommand):
    help = '기존 DB 영화들의 backdrop_path(가로 배경 이미지)만 초고속으로 채워넣기'

    def handle(self, *args, **options):
        # 🔑 TMDB API Key 불러오기
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        if not API_KEY:
            self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY를 찾을 수 없습니다. .env 파일을 확인해 주세요."))
            return

        self.stdout.write(self.style.WARNING("🔥 가로 배경 이미지(Backdrop) 전용 복구 크롤러를 가동합니다..."))

        # 💡 [핵심] 전체 영화를 다 뒤지는 게 아니라, 배경 이미지가 없는(Null이거나 빈 칸인) 영화들만 타겟으로 잡습니다.
        target_movies = Movie.objects.filter(
            Q(backdrop_path__isnull=True) | Q(backdrop_path__exact='')
        )
        total_count = target_movies.count()

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("✨ 모든 영화에 이미 배경 이미지가 채워져 있습니다. 작업할 내용이 없습니다!"))
            return

        self.stdout.write(self.style.NOTICE(f"🎯 총 {total_count}개의 영화에 가로 배경 이미지를 업데이트합니다..."))

        start_time = time.time()
        updated_count = 0

        # 💡 타겟 영화들을 하나씩 돌면서 TMDB에 딱 한 번씩만 물어봅니다.
        for idx, movie in enumerate(target_movies, 1):
            # 회원님의 기존 로직(id=tmdb_id)에 맞춰 movie.id를 TMDB ID로 사용합니다.
            detail_url = f"https://api.themoviedb.org/3/movie/{movie.id}?api_key={API_KEY}&language=ko-KR"
            data = self.fetch_url(detail_url)

            if data:
                backdrop_path = data.get('backdrop_path')
                
                # 💡 가로 이미지가 존재하면 업데이트!
                if backdrop_path:
                    movie.backdrop_path = backdrop_path
                    # 통째로 덮어쓰지 않고, 오직 'backdrop_path' 칸 하나만 쏙 업데이트해서 속도를 극한으로 끌어올립니다.
                    movie.save(update_fields=['backdrop_path'])
                    updated_count += 1

            # 💡 진행 상황을 50개마다 한 번씩 터미널에 예쁘게 출력해줍니다.
            if idx % 50 == 0 or idx == total_count:
                elapsed_seconds = time.time() - start_time
                avg_time = elapsed_seconds / idx
                remaining = avg_time * (total_count - idx)
                
                elapsed_str = self.format_time(elapsed_seconds)
                remaining_str = self.format_time(remaining)
                
                progress = (idx / total_count) * 100
                self.stdout.write(self.style.HTTP_INFO(
                    f"  ↳ 진행 중: {idx}/{total_count} 완료 ({progress:.1f}%) | "
                    f"추가됨: {updated_count}개 | 경과: {elapsed_str} | 남은 시간: {remaining_str}"
                ))

        self.stdout.write(self.style.SUCCESS(f"\n🎉 작업 완료! 텅 비어있던 {updated_count}개의 영화에 고화질 배경 이미지가 성공적으로 추가되었습니다."))

    # --- 기존에 쓰시던 훌륭한 헬퍼 메서드들 그대로 유지 ---
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

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}시간 {minutes}분 {secs}초"
        return f"{minutes}분 {secs}초"