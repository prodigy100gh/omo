import os
import subprocess

# 현재 폴더(BASE_DIR) 기준으로 탐색
base_dir = os.path.dirname(os.path.abspath(__file__))

def run_loaddata(prefix, count):
    for i in range(1, count + 1):
        filename = f"{prefix}_part_{i:02d}.json"
        filepath = os.path.join(base_dir, filename)
        
        if os.path.exists(filepath):
            print(f"📦 [{filename}] 로드 시작...")
            # python manage.py loaddata 파일명 실행
            result = subprocess.run(["python", "manage.py", "loaddata", filename], capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ [{filename}] 로드 성공!")
            else:
                print(f"❌ [{filename}] 에러 발생:\n{result.stderr}")
        else:
            print(f"⚠️ [{filename}] 파일을 찾을 수 없습니다.")

if __name__ == "__main__":
    print("🚀 데이터 순차 로딩 시작!")
    # 영화 18개, TV 8개 순서대로 실행
    run_loaddata("movie_data", 18)
    run_loaddata("tv_data", 8)
    print("🎉 모든 데이터 로딩 완료!")