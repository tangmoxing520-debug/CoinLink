# 推送到 GitHub 的步骤

## ✅ 已完成

- ✅ Git 已安装（版本 2.53.0）
- ✅ Git 仓库已初始化
- ✅ 代码已提交到本地仓库（分支：main）

## 📋 推送到 GitHub

### 步骤1：在 GitHub 上创建新仓库

1. 访问：https://github.com/new
2. 输入仓库名称（例如：`CoinLink`）
3. 选择 Public 或 Private
4. **重要**：不要勾选 "Initialize this repository with a README"
5. 点击 "Create repository"

### 步骤2：推送代码

在项目目录执行以下命令（替换 YOUR_USERNAME 和 YOUR_REPO_NAME）：

```powershell
cd C:\PythonWork\PythonWork\CoinLink

# 添加远程仓库
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git

# 推送到 GitHub
git push -u origin main
```

### 步骤3：身份验证

如果提示输入用户名和密码：
- **用户名**：你的 GitHub 用户名
- **密码**：使用 Personal Access Token（不是账户密码）

#### 获取 Personal Access Token：

1. 访问：https://github.com/settings/tokens
2. 点击 "Generate new token" -> "Generate new token (classic)"
3. 输入 token 名称（例如：`CoinLink-Push`）
4. 选择权限：勾选 `repo`（完整仓库权限）
5. 点击 "Generate token"
6. **重要**：复制 token（只显示一次）
7. 推送时使用 token 作为密码

## 🔍 验证

```powershell
# 检查远程仓库
git remote -v

# 查看提交历史
git log --oneline -5
```

## 📝 当前提交信息

```
feat: Implement P0 optimizations - partial take profit, max drawdown hard stop, daily loss limit, market anomaly detection
```

## ⚠️ 注意事项

1. **敏感信息已排除**：`config.env` 不会上传到 GitHub
2. **日志文件已排除**：`*.log` 不会上传
3. **回测结果已排除**：`backtest_results/` 不会上传
