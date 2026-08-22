import json
import gzip
import os

def split_json_gz(filepath, chunk_size=2000):
    print(f"{filepath} 쪼개기 시작...")
    
    # 1. 원본 파일 읽기
    with gzip.open(filepath, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    # 2. 파일 이름에서 확장자 분리
    base_name = os.path.basename(filepath)
    name_without_ext = base_name.replace('.json.gz', '')
    
    # 3. 데이터 쪼개서 저장
    total_chunks = (len(data) + chunk_size - 1) // chunk_size
    
    for i in range(total_chunks):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size
        chunk_data = data[start_idx:end_idx]
        
        # 새로운 파일 이름 (예: movie_data_part_01.json)
        # 렌더 서버가 쉽게 읽도록 압축은 풀고 일반 json으로 저장합니다.
        new_filename = f"{name_without_ext}_part_{i+1:02d}.json"
        
        with open(new_filename, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, ensure_ascii=False)
            
        print(f"[{i+1}/{total_chunks}] {new_filename} 저장 완료! (데이터 {len(chunk_data)}개)")

    print(f"{filepath} 쪼개기 완료!\n")

# 실행
split_json_gz('movie_data.json.gz')
split_json_gz('tv_data.json.gz')