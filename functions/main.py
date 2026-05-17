from firebase_functions import https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app

set_global_options(max_instances=10)

initialize_app()
@https_fn.on_request()
def process_github_data(req: https_fn.Request) -> https_fn.Response:
    # GitHub API 수집 JSON 정규화 로직
    github_data = req.get_json()

    if not github_data:
        return https_fn.Response("데이터가 없습니다.", status=400)
    
    username = github_data.get("user", {}).get("username", "Unknown")
    language_stats = github_data.get("summary", {}).get("language_percentages", {})

    used_frameworks = set()
    total_commits = 0
    total_additions = 0

    for repo in github_data.get("repositories", []):
        # 프레임워크 추출
        frameworks = repo.get("framework_library_analysis", {}).get("detected_frameworks_libraries", {})
        for category, libs in frameworks.items():
            used_frameworks.update(libs)
        
        # 기여도 추출
        contribution = repo.get("contribution", {})
        total_commits += contribution.get("commit_count_sampled", 0)
        total_additions += contribution.get("total_additions_sampled", 0)

    # DB에 저장하고 정제된 데이터 딕셔너리 생성
    refined_data = {
        "username": username,
        "main_languages": language_stats,           # ex: {"Dart": 41.18, "Python": 18.2}
        "tech_stacks": list(used_frameworks),       # ex: ["react", "express", "openai", "firebase"]
        "activity_level": {
            "total_recent_commits": total_commits,
            "total_code_additions": total_additions
        }
    }

    # Firestore DB에 정제된 데이터 저장
    db = firestore.client()

    db.collection("team_github_metrics").document(username).set(refined_data)
    
    return https_fn.Response(f"{username}님의 GitHub 데이터 정제 및 DB 저장 완료")


@https_fn.on_request()
def github_webhook(req: https_fn.Request) -> https_fn.Response:
    # 깃허브에서 실시간으로 변경 데이터 JSON 받기
    payload = req.get_json()
    
    # Push 이벤트인지, Pull Request 이벤트인지 확인 가능
    event_type = req.headers.get('X-GitHub-Event')

    if event_type == 'push':
        # 이 payload를 파싱해서 누가 어떤 코드를 수정했는지 분석
        # 분석된 결과를 Firestore에 실시간 업데이트
        pass

    return https_fn.Response("Webhook 실시간 수신 완료!")