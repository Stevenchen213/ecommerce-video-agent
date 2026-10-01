# 将本地主架构同步到仓库的「周思含」目录（不碰路遥等人目录）
$ErrorActionPreference = "Stop"

$src = Split-Path -Parent $PSScriptRoot
$dstRoot = "D:\电商视频剪辑AI\_deps\ecommerce-video-agent\周思含"

if (-not (Test-Path "D:\电商视频剪辑AI\_deps\ecommerce-video-agent\.git")) {
    Write-Error "请先 clone: gh repo clone Stevenchen213/ecommerce-video-agent D:\电商视频剪辑AI\_deps\ecommerce-video-agent"
}

New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null

# 只同步我们自己的内容
$items = @(
    "README.md",
    "任务说明.md",
    "缺少清单.md",
    "上传约定.md",
    "启动组装台.bat",
    "video_pipeline"
)

foreach ($name in $items) {
    $from = Join-Path $src $name
    $to = Join-Path $dstRoot $name
    if (-not (Test-Path $from)) {
        Write-Warning "跳过缺失: $from"
        continue
    }
    if (Test-Path $to) {
        Remove-Item -Recurse -Force $to
    }
    Copy-Item -Recurse -Force $from $to
    Write-Host "synced $name"
}

# 清理不应上传的运行时产物（保留 jobs 代码包，只清状态与缓存）
$excludePaths = @(
    "video_pipeline\library",
    "video_pipeline\output",
    "video_pipeline\tmp",
    "video_pipeline\jobs\state.json",
    "video_pipeline\.pytest_cache",
    "video_pipeline\__pycache__",
    ".pytest_cache"
)
foreach ($rel in $excludePaths) {
    $p = Join-Path $dstRoot $rel
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "removed runtime $rel"
    }
}

# 清掉各层 __pycache__
Get-ChildItem $dstRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

# 删除 .env（防密钥）
$envFile = Join-Path $dstRoot "video_pipeline\.env"
if (Test-Path $envFile) {
    Remove-Item -Force $envFile
    Write-Host "removed video_pipeline/.env"
}

Write-Host ""
Write-Host "完成。请到 clone 仓库仅提交周思含："
Write-Host "  cd D:\电商视频剪辑AI\_deps\ecommerce-video-agent"
Write-Host "  git status"
Write-Host "  git add 周思含"
Write-Host "  git commit ..."
Write-Host "  git push"
