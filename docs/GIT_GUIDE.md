# 팀원용 Git 따라하기

OpenResearch 는 **각자 자기 브랜치에서 작업 → 퇴실 전 push → GitHub에서 PR로 main에 합치기 → 모두 main 받기** 순서로 씁니다.
아래 명령은 Windows 명령 프롬프트(cmd) 기준입니다. Mac 은 표시한 줄만 바꾸세요.

> 이 저장소의 기본 브랜치 이름은 `master` 가 아니라 **`main`** 입니다.

## 내 브랜치 이름

| 팀원 | 브랜치 | 작업 폴더 |
|---|---|---|
| CH | `ch` | `members/CH` |
| SW | `sw` | `members/SW` |
| SH | `sh` | `members/SH` |
| JT | `jt` | `members/JT` |

아래 명령의 `내브랜치` 를 위 표의 내 브랜치 이름으로 바꿔서 실행합니다. (예: `git checkout ch`)

---

## 0) 처음 한 번만

```
:: 1. 원하는 폴더로 이동 (경로는 각자)
cd C:\Users\Admin\Desktop\2차

:: 2. 저장소 내려받기
git clone https://github.com/chjogit/OpenResearch.git
cd OpenResearch

:: 3. 내 이름 등록 (커밋에 표시됨)
git config user.name "내 이름"
git config user.email "GitHub 가입 이메일"

:: 4. 내 브랜치 만들고 GitHub에 올리기
git checkout -b 내브랜치
git push -u origin 내브랜치

:: 5. 파이썬 환경 (가상환경만 Python 3.12, PC 기본 Python 은 그대로)
pip install uv
uv venv --python 3.12 .venv
.venv\Scripts\activate
uv pip install -r requirements-dev.txt
python -m ipykernel install --user --name openresearch --display-name "Python (openresearch .venv)"
copy .env.example .env
```

- 이미 3.12 가 아닌 `.venv` 가 있으면 `rmdir /s /q .venv` 로 지우고 다시 만듭니다. `python --version` 으로 확인합니다.
- 노트북은 커널을 **Python (openresearch .venv)** 로 골라 실행합니다.

- Mac: `.venv\Scripts\activate` → `source .venv/bin/activate`, `copy` → `cp`
- `.env` 를 메모장으로 열어 DB 주소와 Upstage 키를 채웁니다. `.env` 는 GitHub에 올라가지 않습니다.
- `git` 이 없다고 나오면 https://git-scm.com 에서 Git for Windows 를 설치합니다.

---

## 1) 작업 시작할 때

**항상 내 브랜치에서 작업합니다.**

```
cd C:\Users\Admin\Desktop\2차\OpenResearch
.venv\Scripts\activate
git branch
```

`* 내브랜치` 처럼 내 브랜치에 `*` 가 있으면 됩니다. 아니면 `git checkout 내브랜치`.

내 코드는 `members/내폴더` 안에 둡니다. 공용 폴더(`agent/` 등)를 고칠 때는 팀에 먼저 말해 주세요.

---

## 2) 퇴실 전: 내 작업 올리기

```
git branch
git add .
git commit -m "오늘 한 일 한 줄 (예: Peer 비교표 초안)"
git push origin 내브랜치
```

ⓐ `git branch` 로 내 브랜치인지 확인 → ⓑ 바뀐 파일 담기 → ⓒ 이름 붙여 저장 → ⓓ GitHub에 올리기

---

## 3) 팀원 모두 push 후: GitHub에서 합치기 (한 명씩)

1. https://github.com/chjogit/OpenResearch 접속
2. 노란 **Compare & pull request** 버튼, 또는 **Pull requests → New pull request**
3. `base: main` ← `compare: 내브랜치` 확인 → **Create pull request**
4. **Merge pull request → Confirm merge**
5. 다음 사람 브랜치도 같은 방법으로 하나씩 합칩니다.

**충돌(conflict)이 나면:** 같은 파일의 같은 줄을 두 사람이 고친 경우입니다. 억지로 합치지 말고 해당 팀원과 함께 GitHub 화면의 **Resolve conflicts** 에서 남길 내용을 고른 뒤 합칩니다. 각자 자기 `members/` 폴더에서만 작업하면 거의 생기지 않습니다.

---

## 4) 모두 합친 뒤: 최신 main 받기

```
:: ⓐ 내 브랜치에 main 받기
git branch
git pull origin main

:: ⓑ main 브랜치도 최신으로
git checkout main
git pull origin main

:: ⓒ 다시 내 브랜치로 돌아오기
git checkout 내브랜치
```

마지막에 `git branch` 로 내 브랜치에 돌아왔는지 확인하고 퇴실 태그 부탁드립니다.

---

## 자주 막히는 곳

| 증상 | 해결 |
|---|---|
| `git push` 에서 로그인 창이 뜸 | GitHub 계정으로 로그인 (브라우저 창에서 승인) |
| `nothing to commit` | 바뀐 파일이 없다는 뜻. 그대로 다음 단계로 |
| `rejected ... fetch first` | `git pull origin 내브랜치` 후 다시 `git push origin 내브랜치` |
| `pull` 중 편집기 화면(vim)이 뜸 | `:wq` 입력 후 Enter |
| `CONFLICT` 메시지 | 충돌 파일을 열어 `<<<<<<<`~`>>>>>>>` 부분에서 남길 내용만 두고 저장 → `git add .` → `git commit -m "충돌 해결"` |
| 실수로 main 에서 작업함 | 커밋 전이면 `git checkout 내브랜치` (바뀐 내용이 따라옵니다) |

## 하지 말 것

- `.env`, API 키, DB 주소를 커밋하기
- `git push origin main` 처럼 main 에 직접 올리기
- `git push --force`
