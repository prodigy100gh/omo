import os
import time
import requests
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from movie.models import TvSeries

class Command(BaseCommand):
    help = '기존 TV 시리즈 데이터에 tmdb_status(종영 여부)만 빠르게 업데이트합니다.'

    def handle(self, *args, **options):
        load_dotenv()
        API_KEY = os.getenv("TMDB_API_KEY")

        # 💡 tmdb_status가 비어있는(아직 업데이트 안 된) 시리즈만 골라냅니다.
        target_series = TvSeries.objects.filter(tmdb_status__isnull=True) | TvSeries.objects.filter(tmdb_status='')
        total_count = target_series.count()

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("🎉 모든 TV 시리즈의 상태(status)가 이미 최신입니다!"))
            return

        self.stdout.write(self.style.WARNING(f"🔥 총 {total_count}개의 TV 시리즈 상태 업데이트를 시작합니다..."))

        updated_count = 0
        for index, series in enumerate(target_series, 1):
            # 상태값만 가져오면 되므로 가볍게 기본 정보만 요청합니다.
            url = f"https://api.themoviedb.org/3/tv/{series.id}?api_key={API_KEY}&language=ko-KR"
            
            try:
                res = requests.get(url, timeout=10)
                
                if res.status_code == 200:
                    data = res.json()
                    status_val = data.get('status', 'Unknown')
                    
                    # 💡 DB 업데이트
                    series.tmdb_status = status_val
                    series.save(update_fields=['tmdb_status'])
                    
                    updated_count += 1
                    self.stdout.write(f"[{index}/{total_count}] {series.tmdb_title} ➔ {status_val}")
                    
                elif res.status_code == 429:
                    self.stdout.write(self.style.WARNING("⚠️ API 제한! 3초 대기..."))
                    time.sleep(3)
                else:
                    self.stdout.write(self.style.ERROR(f"[{index}/{total_count}] {series.tmdb_title} 조회 실패 (코드: {res.status_code})"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[{index}/{total_count}] {series.tmdb_title} 에러 발생: {e}"))

            # TMDB 서버에 무리가 가지 않도록 아주 짧은 휴식
            time.sleep(0.05)

        self.stdout.write(self.style.SUCCESS(f"\n✅ 완벽하게 끝났습니다! 총 {updated_count}개의 데이터가 업데이트되었습니다."))