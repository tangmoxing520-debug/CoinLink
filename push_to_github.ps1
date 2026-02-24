# GitHub 推送脚本
# 使用方法：.\push_to_github.ps1 -Username YOUR_USERNAME -RepoName YOUR_REPO_NAME

param(
    [Parameter(Mandatory=$true)]
    [string]$Username,
    
    [Parameter(Mandatory=$true)]
    [string]$RepoName
)

Write-Host "=== 推送到 GitHub ===" -ForegroundColor Green
Write-Host ""

# 检查是否已有远程仓库
$remote = git remote get-url origin 2>$null
if ($remote) {
    Write-Host "⚠️  已存在远程仓库: $remote" -ForegroundColor Yellow
    $confirm = Read-Host "是否要更新远程仓库URL? (y/n)"
    if ($confirm -eq 'y') {
        git remote set-url origin "https://github.com/$Username/$RepoName.git"
        Write-Host "✅ 远程仓库URL已更新" -ForegroundColor Green
    }
} else {
    # 添加远程仓库
    git remote add origin "https://github.com/$Username/$RepoName.git"
    Write-Host "✅ 已添加远程仓库: https://github.com/$Username/$RepoName.git" -ForegroundColor Green
}

Write-Host ""
Write-Host "准备推送到 GitHub..." -ForegroundColor Cyan
Write-Host "仓库: https://github.com/$Username/$RepoName.git" -ForegroundColor Cyan
Write-Host ""

# 检查当前分支
$branch = git branch --show-current
Write-Host "当前分支: $branch" -ForegroundColor Cyan

# 推送
Write-Host ""
Write-Host "正在推送..." -ForegroundColor Yellow
Write-Host "提示: 如果要求身份验证，请使用 Personal Access Token 作为密码" -ForegroundColor Yellow
Write-Host ""

try {
    git push -u origin $branch
    Write-Host ""
    Write-Host "✅ 推送成功！" -ForegroundColor Green
    Write-Host "仓库地址: https://github.com/$Username/$RepoName" -ForegroundColor Cyan
} catch {
    Write-Host ""
    Write-Host "❌ 推送失败" -ForegroundColor Red
    Write-Host "错误信息: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "请检查:" -ForegroundColor Yellow
    Write-Host "1. GitHub 仓库是否已创建" -ForegroundColor Yellow
    Write-Host "2. 是否使用了正确的用户名和仓库名" -ForegroundColor Yellow
    Write-Host "3. 是否已配置身份验证（Personal Access Token）" -ForegroundColor Yellow
}
