from firebase_admin import firestore
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

    if not payload:
        return https_fn.Response("Webhook payload가 없습니다.", status=400)
    
    # Push 이벤트인지, Pull Request 이벤트인지 확인 가능
    event_type = req.headers.get('X-GitHub-Event')

    db = firestore.client()

    if event_type == 'push':
        repository = payload.get("repository", {})
        pusher = payload.get("pusher", {})
        sender = payload.get("sender", {})

        repo_name = repository.get("name", "")
        repo_full_name = repository.get("full_name", "")
        repo_url = repository.get("html_url", "")
        branch_ref = payload.get("ref", "")
        branch_name = branch_ref.replace("refs/heads/", "")

        pusher_name = pusher.get("name") or sender.get("login") or "Unknown"
        pusher_email = pusher.get("email", "")

        commits = payload.get("commits", [])

        extracted_commits = []

        for commit in commits:
            commit_id = commit.get("id", "")
            commit_message = commit.get("message", "")
            commit_url = commit.get("url", "")
            timestamp = commit.get("timestamp", "")

            author = commit.get("author", {})
            author_name = author.get("name", pusher_name)
            author_email = author.get("email", pusher_email)
            author_username = author.get("username", "")

            added_files = commit.get("added", [])
            modified_files = commit.get("modified", [])
            removed_files = commit.get("removed", [])

            changed_files = {
                "added": added_files,
                "modified": modified_files,
                "removed": removed_files,
                "all": added_files + modified_files + removed_files
            }

            extracted_commits.append({
                "commit_id": commit_id,
                "message": commit_message,
                "commit_url": commit_url,
                "timestamp": timestamp,
                "author": {
                    "name": author_name,
                    "email": author_email,
                    "username": author_username
                },
                "changed_files": changed_files
            })

        workflow_context = {
            "event_type": "push",
            "repository": {
                "name": repo_name,
                "full_name": repo_full_name,
                "url": repo_url,
                "branch": branch_name
            },
            "pusher": {
                "name": pusher_name,
                "email": pusher_email
            },
            "summary": {
                "commit_count": len(extracted_commits),
                "changed_file_count": sum(
                    len(commit["changed_files"]["all"])
                    for commit in extracted_commits
                )
            },
            "commits": extracted_commits,
            "received_at": firestore.SERVER_TIMESTAMP
        }

        # ai_workflow_context 컬렉션에 이벤트 단위로 저장
        doc_ref = db.collection("ai_workflow_context").document()
        doc_ref.set(workflow_context)

        return https_fn.Response(
            f"Push 이벤트 저장 완료: {repo_full_name}, commits={len(extracted_commits)}",
            status=200
        )

    return https_fn.Response("Webhook 실시간 수신 완료!")