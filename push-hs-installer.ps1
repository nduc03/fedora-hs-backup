$ErrorActionPreference = "Stop"

# 1. Kiểm tra nếu có thay đổi chưa commit trong refactor-install-py
$uncommitted = git status --porcelain refactor-install-py
if ($uncommitted) {
    Write-Warning "Cảnh báo: Có thay đổi chưa commit trong thư mục refactor-install-py!"
    Write-Host "Vui lòng commit các thay đổi trên nhánh hiện tại trước khi push." -ForegroundColor Yellow
    exit 1
}

# 2. Lấy hash tree của refactor-install-py tại HEAD
$tree = (git rev-parse HEAD:refactor-install-py).Trim()
$installerBranch = "installer"
$remoteName = "hs-installer-repo"

# 3. Lấy hash commit và tree hiện tại của nhánh installer
$installerCommit = (git rev-parse $installerBranch).Trim()
$installerTree = (git rev-parse "${installerBranch}:").Trim()

if ($tree -ne $installerTree) {
    Write-Host "Phát hiện thay đổi mới trong refactor-install-py..." -ForegroundColor Cyan
    # Lấy message của commit gần nhất trên HEAD
    $commitMsg = (git log -1 --format=%B HEAD).Trim()
    
    # Tạo commit mới cho nhánh installer với tree của refactor-install-py
    $newCommit = (git commit-tree $tree -p $installerCommit -m $commitMsg).Trim()
    
    # Cập nhật con trỏ nhánh installer
    git update-ref "refs/heads/$installerBranch" $newCommit
    Write-Host "Đã tạo commit $newCommit trên nhánh $installerBranch." -ForegroundColor Green
} else {
    Write-Host "Nhánh $installerBranch đã đồng bộ với refactor-install-py." -ForegroundColor Cyan
}

# 4. Push lên remote hs-installer-repo
Write-Host "Đang push sang $remoteName..." -ForegroundColor Cyan
git push $remoteName "${installerBranch}:main"
