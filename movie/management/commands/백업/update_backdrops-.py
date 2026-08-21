import concurrent.futures
import requests
import time
from django.core.management.base import BaseCommand
from django.db.models import Q
from movie.models import Movie  # 앱 이름(movie)에 맞춰 수정하세요
import os
from dotenv import load_dotenv

class Command(BaseCommand):
    help = '멀티스레딩과 벌크 업데이트를 이용한 backdrop_path 초고속 복구 크롤러'

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        if not API_KEY:
            self.stdout.write(self.style.ERROR("❌ TMDB_API_KEY를 찾을 수 없습니다. .env 파일을 확인해 주세요."))
            return

        self.stdout.write(self.style.WARNING("🔥 [초고속] 멀티스레딩 + Bulk Update 배경 이미지 크롤러를 가동합니다..."))

        # 1. 대상 영화의 ID만 빠르게 싹 끌어옵니다. (메모리 절약)
        target_movie_ids = list(Movie.objects.filter(
            Q(backdrop_path__isnull=True) | Q(backdrop_path__exact='')
        ).values_list('id', flat=True))

        total_count = len(target_movie_ids)

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("✨ 모든 영화에 이미 배경 이미지가 채워져 있습니다. 작업할 내용이 없습니다!"))
            return

        self.stdout.write(self.style.NOTICE(f"🎯 총 {total_count}개의 영화 대상 초고속 처리 시작..."))

        start_time = time.time()
        updated_count = 0
        processed_count = 0
        
        # ⚙️ 설정값
        max_workers = 25     # 동시에 요청할 스레드 수 (TMDB 서버 부하를 고려해 20~30 사이가 적당합니다)
        batch_size = 500     # DB에 한 번에 뭉쳐서 업데이트할 단위

        # 스레드 안에서 실행될 개별 API 호출 함수 (네트워크 I/O 병렬 처리)
        def fetch_backdrop(movie_id):
            url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={API_KEY}&language=ko-KR"
            for _ in range(3):  # 실패 시 최대 3번 재시도
                try:
                    res = requests.get(url, timeout=5)
                    if res.status_code == 200:
                        data = res.json()
                        return movie_id, data.get('backdrop_path')
                    elif res.status_code == 429:
                        time.sleep(1.5)  # API 제한 걸리면 잠시 숨고르기
                    else:
                        break
                except Exception:
                    time.sleep(1)
            return movie_id, None

        movies_to_update = []

        # 2. 멀티스레딩 풀(Pool)을 열어서 병렬로 API 폭격 시작
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {executor.submit(fetch_backdrop, m_id): m_id for m_id in target_movie_ids}
            
            for future in concurrent.futures.as_completed(future_to_id):
                processed_count += 1
                movie_id, backdrop_path = future.result()

                if backdrop_path:
                    movies_to_update.append((movie_id, backdrop_path))

                # 3. 배치가 찼거나 마지막 작업일 때 bulk_update 실행 (DB 부하 최소화)
                if len(movies_to_update) >= batch_size or processed_count == total_count:
                    if movies_to_update:
                        # 해당 아이디들의 객체를 한 번에 불러옴
                        batch_ids = [item[0] for item in movies_to_update]
                        path_map = {item[0]: item[1] for item in movies_to_update}
                        
                        objs = Movie.objects.filter(id__in=batch_ids)
                        update_list = []
                        for obj in objs:
                            if obj.id in path_map:
                                obj.backdrop_path = path_map[obj.id]
                                update_list.append(obj)
                        
                        if update_list:
                            # 💡 핵심: 개별 save()가 아닌 bulk_update로 한 방에 쿼리 전송
                            Movie.objects.bulk_update(update_list, ['backdrop_path'])
                            updated_count += len(update_list)
                            
                        movies_to_update = []

                # 4. 진행 상황 출력 (100개 단위 또는 완료 시)
                if processed_count % 100 == 0 or processed_count == total_count:
                    elapsed_seconds = time.time() - start_time
                    avg_time = elapsed_seconds / processed_count
                    remaining = avg_time * (total_count - processed_count)
                    
                    elapsed_str = self.format_time(elapsed_seconds)
                    remaining_str = self.format_time(remaining)
                    
                    progress = (processed_count / total_count) * 100
                    self.stdout.write(self.style.HTTP_INFO(
                        f"  ↳ 진행 중: {processed_count}/{total_count} 완료 ({progress:.1f}%) | "
                        f"업데이트 됨: {updated_count}개 | 경과: {elapsed_str} | 남은 시간: {remaining_str}"
                    ))

        self.stdout.write(self.style.SUCCESS(f"\n🎉 초고속 작업 완료! 총 {updated_count}개의 영화 배경 이미지가 눈 깜짝할 사이에 추가되었습니다."))

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}시간 {minutes}분 {secs}초"
        return f"{minutes}분 {secs}초"