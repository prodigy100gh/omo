import os
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

class Command(BaseCommand):
    help = '쪼개진 영화/TV 데이터를 순차적으로 로드합니다.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("🚀 데이터 순차 로딩 시작!"))
        
        # 프로젝트의 최상단 폴더 경로를 꽉 잡습니다.
        base_dir = settings.BASE_DIR

        # 영화 파일 18개
        for i in range(1, 19):
            filename = f"movie_data_part_{i:02d}.json"
            filepath = os.path.join(base_dir, filename) # 절대 경로 생성
            self.stdout.write(f"📦 [{filename}] 로드 시작...")
            try:
                call_command('loaddata', filepath)
                self.stdout.write(self.style.SUCCESS(f"✅ [{filename}] 완료!"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"❌ [{filename}] 에러: {e}"))

        # TV 파일 8개
        for i in range(1, 9):
            filename = f"tv_data_part_{i:02d}.json"
            filepath = os.path.join(base_dir, filename) # 절대 경로 생성
            self.stdout.write(f"📦 [{filename}] 로드 시작...")
            try:
                call_command('loaddata', filepath)
                self.stdout.write(self.style.SUCCESS(f"✅ [{filename}] 완료!"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"❌ [{filename}] 에러: {e}"))

        self.stdout.write(self.style.SUCCESS("🎉 모든 데이터 로딩 완료!"))