# OpenResearch sw 브랜치를 ai-mbc 토큰으로 올리기 (로그인 창 없이). 토큰은 가려진 칸에 입력, 파일·설정·화면 어디에도 남기지 않음
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location 'D:\AI\Projects\OpenResearch'
$b = (git branch --show-current).Trim()
if ($b -ne 'sw') { Write-Host "지금 브랜치가 sw 가 아닙니다($b). PR_1 을 먼저 실행하세요."; Read-Host 'Enter 로 닫기'; exit 1 }
git remote set-url origin https://github.com/chjogit/OpenResearch.git
Write-Host 'ai-mbc 토큰(ghp_로 시작)을 붙여 넣고 Enter (입력한 글자는 보이지 않습니다)'
$sec = Read-Host -AsSecureString '토큰'
$tok = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("ai-mbc:$tok"))
$tok = $null
git -c credential.helper= -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $basic" push -u origin sw
$code = $LASTEXITCODE; $basic = $null
if ($code -eq 0) {
  Write-Host "`n올리기 완료. PR 만들기 화면을 엽니다."
  Start-Process 'https://github.com/chjogit/OpenResearch/compare/main...sw?expand=1'
} else {
  Write-Host "`n올리기 실패(위 글 참고). 403 / denied 이면 ai-mbc 에 쓰기 권한이 없는 것 → 철현님께 Collaborator 추가 요청."
}
Read-Host 'Enter 로 닫기'
