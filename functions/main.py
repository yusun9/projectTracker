from firebase_functions import https_fn
from firebase_functions.options import set_global_options
from firebase_admin import initialize_app

set_global_options(max_instances=10)

initialize_app()
@https_fn.on_request()
def process_github_data(req: https_fn.Request) -> https_fn.Response:
    # GitHub API 수집 및 JSON 정규화 로직 아래에 합치기
    # 프론트에서 넘어온 req 데이터에서 github_url 등 추출해서 작성
    
    return https_fn.Response("GitHub 데이터 수집 API 통로 준비 완료")