# GitHub Token 필요.
# 현재는 local 작동 전제로 구성. 이후 연결 필요.
# max repos 10으로 제한해서 보도록 제한 중 -> 향후 레포 수 조정.

import os
import re
import json
import base64
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()


class GitHubAnalyzer:
    BASE_URL = "https://api.github.com"

    DEPENDENCY_FILES = [
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "package.json",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
        "Gemfile",
        "go.mod",
    ]

    FRAMEWORK_KEYWORDS = {
        "frontend": [
            "react", "next", "nextjs", "vue", "nuxt", "svelte",
            "vite", "webpack", "tailwind", "bootstrap"
        ],
        "backend": [
            "fastapi", "flask", "django", "spring", "spring-boot",
            "express", "nestjs", "laravel", "rails", "gin", "fiber"
        ],
        "ai_ml": [
            "torch", "pytorch", "tensorflow", "keras", "sklearn",
            "scikit-learn", "pandas", "numpy", "transformers",
            "langchain", "openai", "upstage"
        ],
        "database": [
            "mysql", "postgresql", "postgres", "sqlite",
            "mongodb", "mongoose", "redis", "firebase", "firestore"
        ],
        "devops": [
            "docker", "docker-compose", "kubernetes", "github actions",
            "ci", "cd", "nginx"
        ],
        "security": [
            "wazuh", "suricata", "yara", "wireshark", "nmap",
            "metasploit", "cve", "cwe", "exploit", "vulnerability"
        ],
    }

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.session = requests.Session()

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "projectTracker-github-analyzer",
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        self.session.headers.update(headers)

    # -----------------------------
    # 공통 요청 함수
    # -----------------------------

    def _get(self, path_or_url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = f"{self.BASE_URL}{path_or_url}"

        response = self.session.get(url, params=params, timeout=20)

        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise RuntimeError("GitHub API rate limit에 걸렸습니다. GITHUB_TOKEN을 설정하거나 잠시 후 다시 시도하세요.")

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()

    def _get_paginated(self, path: str, params: Optional[Dict[str, Any]] = None, max_pages: int = 5) -> List[Any]:
        results = []
        page = 1

        while page <= max_pages:
            merged_params = dict(params or {})
            merged_params.update({"per_page": 100, "page": page})

            data = self._get(path, merged_params)

            if not data:
                break

            if isinstance(data, list):
                results.extend(data)
                if len(data) < 100:
                    break
            else:
                break

            page += 1
            time.sleep(0.1)

        return results

    # -----------------------------
    # 1. GitHub profile URL에서 username 추출
    # -----------------------------

    def extract_username(self, github_profile_url: str) -> str:
        github_profile_url = github_profile_url.strip()

        if github_profile_url.startswith("@"):
            return github_profile_url[1:]

        if "github.com" not in github_profile_url:
            return github_profile_url.strip("/")

        parsed = urlparse(github_profile_url)
        path_parts = [part for part in parsed.path.split("/") if part]

        if not path_parts:
            raise ValueError("GitHub profile URL에서 username을 찾을 수 없습니다.")

        username = path_parts[0]

        blocked_paths = {"orgs", "topics", "features", "marketplace", "explore"}
        if username in blocked_paths:
            raise ValueError("개인 GitHub profile URL 형식이 아닙니다.")

        return username

    # -----------------------------
    # 2. public repo 목록 조회
    # -----------------------------

    def get_public_repos(self, username: str, max_repos: int = 20) -> List[Dict[str, Any]]:
        repos = self._get_paginated(
            f"/users/{username}/repos",
            params={
                "type": "owner",
                "sort": "updated",
                "direction": "desc",
            },
            max_pages=3,
        )

        public_repos = [
            repo for repo in repos
            if not repo.get("private") and not repo.get("fork")
        ]

        return public_repos[:max_repos]

    # -----------------------------
    # 3. repo별 language 조회
    # -----------------------------

    def get_languages(self, owner: str, repo: str) -> Dict[str, int]:
        data = self._get(f"/repos/{owner}/{repo}/languages")
        return data or {}

    # -----------------------------
    # 4. repo별 README 조회
    # -----------------------------

    def get_readme(self, owner: str, repo: str) -> Optional[str]:
        data = self._get(f"/repos/{owner}/{repo}/readme")

        if not data or "content" not in data:
            return None

        try:
            content = data["content"]
            decoded = base64.b64decode(content).decode("utf-8", errors="replace")
            return decoded[:10000]
        except Exception:
            return None

    # -----------------------------
    # 5. repo별 파일 트리 조회
    # -----------------------------

    def get_file_tree(self, owner: str, repo: str, default_branch: str, max_files: int = 300) -> List[Dict[str, Any]]:
        branch = self._get(f"/repos/{owner}/{repo}/branches/{default_branch}")
        if not branch:
            return []

        tree_sha = branch["commit"]["commit"]["tree"]["sha"]

        tree_data = self._get(
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )

        if not tree_data or "tree" not in tree_data:
            return []

        files = []
        for item in tree_data["tree"]:
            if item.get("type") == "blob":
                files.append({
                    "path": item.get("path"),
                    "size": item.get("size"),
                })

        return files[:max_files]

    # -----------------------------
    # 파일 내용 조회
    # -----------------------------

    def get_file_content(self, owner: str, repo: str, path: str) -> Optional[str]:
        data = self._get(f"/repos/{owner}/{repo}/contents/{path}")

        if not data or data.get("type") != "file":
            return None

        if "content" not in data:
            return None

        try:
            decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return decoded[:15000]
        except Exception:
            return None

    # -----------------------------
    # 3. 프레임워크/라이브러리 추론
    # -----------------------------

    def infer_frameworks_and_libraries(
        self,
        owner: str,
        repo: str,
        file_tree: List[Dict[str, Any]],
        readme: Optional[str],
    ) -> Dict[str, Any]:
        paths = [item["path"] for item in file_tree]
        lower_paths = [path.lower() for path in paths]

        dependency_file_paths = [
            path for path in paths
            if path.split("/")[-1] in self.DEPENDENCY_FILES
        ]

        dependency_texts = {}
        for path in dependency_file_paths[:10]:
            content = self.get_file_content(owner, repo, path)
            if content:
                dependency_texts[path] = content

        combined_text = "\n".join([
            readme or "",
            "\n".join(paths),
            "\n".join(dependency_texts.values()),
        ]).lower()

        detected = {
            "frontend": [],
            "backend": [],
            "ai_ml": [],
            "database": [],
            "devops": [],
            "security": [],
        }

        for category, keywords in self.FRAMEWORK_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in combined_text:
                    detected[category].append(keyword)

        project_signals = {
            "has_docker": any("dockerfile" in p or "docker-compose" in p for p in lower_paths),
            "has_github_actions": any(".github/workflows" in p for p in lower_paths),
            "has_tests": any(
                p.startswith("test/") or p.startswith("tests/") or "/test/" in p or "/tests/" in p
                for p in lower_paths
            ),
            "has_frontend_config": any(
                p.endswith("package.json") or p.endswith("vite.config.js") or p.endswith("next.config.js")
                for p in lower_paths
            ),
            "has_python_project": any(
                p.endswith("requirements.txt") or p.endswith("pyproject.toml")
                for p in lower_paths
            ),
            "has_java_project": any(
                p.endswith("pom.xml") or p.endswith("build.gradle") or p.endswith("build.gradle.kts")
                for p in lower_paths
            ),
            "has_rust_project": any(p.endswith("cargo.toml") for p in lower_paths),
        }

        return {
            "dependency_files": list(dependency_texts.keys()),
            "detected_frameworks_libraries": detected,
            "project_signals": project_signals,
        }

    # -----------------------------
    # 6. repo별 기여도 조회
    # -----------------------------

    def get_repo_contribution(
        self,
        owner: str,
        repo: str,
        username: str,
        max_commits: int = 30,
    ) -> Dict[str, Any]:
        commits = self._get_paginated(
            f"/repos/{owner}/{repo}/commits",
            params={"author": username},
            max_pages=2,
        )

        commits = commits[:max_commits]

        commit_summaries = []
        total_additions = 0
        total_deletions = 0
        touched_files = {}

        for commit in commits:
            sha = commit.get("sha")
            if not sha:
                continue

            detail = self._get(f"/repos/{owner}/{repo}/commits/{sha}")
            if not detail:
                continue

            stats = detail.get("stats", {})
            total_additions += stats.get("additions", 0)
            total_deletions += stats.get("deletions", 0)

            files = detail.get("files", [])
            changed_file_paths = []

            for f in files:
                filename = f.get("filename")
                if not filename:
                    continue

                changed_file_paths.append(filename)

                if filename not in touched_files:
                    touched_files[filename] = {
                        "path": filename,
                        "change_count": 0,
                        "additions": 0,
                        "deletions": 0,
                    }

                touched_files[filename]["change_count"] += 1
                touched_files[filename]["additions"] += f.get("additions", 0)
                touched_files[filename]["deletions"] += f.get("deletions", 0)

            commit_summaries.append({
                "sha": sha,
                "message": detail.get("commit", {}).get("message", "").split("\n")[0],
                "date": detail.get("commit", {}).get("author", {}).get("date"),
                "additions": stats.get("additions", 0),
                "deletions": stats.get("deletions", 0),
                "changed_files": changed_file_paths[:20],
            })

            time.sleep(0.1)

        top_touched_files = sorted(
            touched_files.values(),
            key=lambda x: x["change_count"],
            reverse=True,
        )[:30]

        return {
            "commit_count_sampled": len(commit_summaries),
            "total_additions_sampled": total_additions,
            "total_deletions_sampled": total_deletions,
            "top_touched_files": top_touched_files,
            "recent_commits": commit_summaries,
        }

    # -----------------------------
    # 7. JSON 정규화
    # -----------------------------

    def analyze_profile(self, github_profile_url: str, max_repos: int = 10) -> Dict[str, Any]:
        username = self.extract_username(github_profile_url)

        user_info = self._get(f"/users/{username}")
        if not user_info:
            raise ValueError(f"GitHub user를 찾을 수 없습니다: {username}")

        repos = self.get_public_repos(username, max_repos=max_repos)

        normalized_repos = []
        total_languages: Dict[str, int] = {}

        for repo in repos:
            owner = repo["owner"]["login"]
            repo_name = repo["name"]
            default_branch = repo.get("default_branch") or "main"

            print(f"[분석 중] {owner}/{repo_name}")

            languages = self.get_languages(owner, repo_name)
            for lang, size in languages.items():
                total_languages[lang] = total_languages.get(lang, 0) + size

            readme = self.get_readme(owner, repo_name)
            file_tree = self.get_file_tree(owner, repo_name, default_branch)

            framework_info = self.infer_frameworks_and_libraries(
                owner=owner,
                repo=repo_name,
                file_tree=file_tree,
                readme=readme,
            )

            contribution = self.get_repo_contribution(
                owner=owner,
                repo=repo_name,
                username=username,
            )

            normalized_repos.append({
                "repo_name": repo_name,
                "full_name": repo.get("full_name"),
                "html_url": repo.get("html_url"),
                "description": repo.get("description"),
                "created_at": repo.get("created_at"),
                "updated_at": repo.get("updated_at"),
                "pushed_at": repo.get("pushed_at"),
                "stars": repo.get("stargazers_count"),
                "forks": repo.get("forks_count"),
                "watchers": repo.get("watchers_count"),
                "open_issues": repo.get("open_issues_count"),
                "default_branch": default_branch,
                "main_language": repo.get("language"),
                "languages": languages,
                "readme_summary_source": readme[:2000] if readme else None,
                "file_tree_sample": file_tree[:100],
                "framework_library_analysis": framework_info,
                "contribution": contribution,
            })

            time.sleep(0.2)

        total_language_bytes = sum(total_languages.values())
        language_percentages = {}

        if total_language_bytes > 0:
            language_percentages = {
                lang: round((size / total_language_bytes) * 100, 2)
                for lang, size in sorted(total_languages.items(), key=lambda x: x[1], reverse=True)
            }

        result = {
            "input": {
                "github_profile_url": github_profile_url,
            },
            "user": {
                "username": username,
                "name": user_info.get("name"),
                "bio": user_info.get("bio"),
                "public_repos": user_info.get("public_repos"),
                "followers": user_info.get("followers"),
                "following": user_info.get("following"),
                "created_at": user_info.get("created_at"),
                "updated_at": user_info.get("updated_at"),
            },
            "summary": {
                "analyzed_repo_count": len(normalized_repos),
                "total_languages_bytes": total_languages,
                "language_percentages": language_percentages,
            },
            "repositories": normalized_repos,
        }

        return result


def save_json(data: Dict[str, Any], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    analyzer = GitHubAnalyzer()

    github_url = input("GitHub profile URL을 입력하세요: ").strip()

    result = analyzer.analyze_profile(
        github_profile_url=github_url,
        max_repos=10,
    )

    username = result["user"]["username"]
    output_file = f"{username}_github_profile_analysis.json"

    save_json(result, output_file)

    print(f"\n분석 완료: {output_file}")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))