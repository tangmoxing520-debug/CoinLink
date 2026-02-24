# Git 提交指南

## 当前状态

- ❌ Git 未安装或不在 PATH 中
- ❌ 项目目录尚未初始化 Git 仓库

## 解决方案

### 方案1：安装 Git（推荐）

1. **下载并安装 Git**
   - 访问：https://git-scm.com/download/win
   - 下载 Windows 版本并安装
   - 安装时选择"Add Git to PATH"

2. **验证安装**
   ```powershell
   git --version
   ```

3. **初始化仓库并提交**
   ```powershell
   cd C:\PythonWork\PythonWork\CoinLink
   git init
   git add .
   git commit -m "feat: 实施P0优化项 - 分批止盈、最大回撤硬止损、单日亏损限制、市场异常检测"
   ```

### 方案2：使用 GitHub Desktop（图形界面）

1. 下载并安装 GitHub Desktop：https://desktop.github.com/
2. 打开 GitHub Desktop
3. 选择 "File" -> "Add Local Repository"
4. 选择项目目录：`C:\PythonWork\PythonWork\CoinLink`
5. 点击 "Publish repository" 或直接提交

### 方案3：手动操作步骤

如果已安装 Git 但不在 PATH 中，可以：

1. **找到 Git 安装路径**（通常在 `C:\Program Files\Git\bin\git.exe`）

2. **使用完整路径执行命令**
   ```powershell
   cd C:\PythonWork\PythonWork\CoinLink
   & "C:\Program Files\Git\bin\git.exe" init
   & "C:\Program Files\Git\bin\git.exe" add .
   & "C:\Program Files\Git\bin\git.exe" commit -m "feat: 实施P0优化项"
   ```

## 推荐的提交信息

```bash
git commit -m "feat: 实施P0优化项 - 分批止盈、最大回撤硬止损、单日亏损限制、市场异常检测

- 实现分批止盈策略（10%/20%/30%三级止盈）
- 实现最大回撤硬止损（20%暂停，30%停止）
- 实现单日亏损限制（5%暂停，10%停止）
- 实现市场异常检测（闪崩保护、流动性检测）
- 优化流动性检测逻辑，减少误报
- 修复K线数据时间戳处理问题
- 修复time模块导入缺失问题
- 更新配置文件和文档"
```

## 主要更改文件

### 核心功能文件
- `trader_v2.py` - 添加分批止盈、风险控制逻辑
- `live_trader_v3.py` - 添加市场异常检测
- `config.py` - 添加P0优化配置参数

### 配置文件
- `config.env` - 更新P0优化配置
- `config.env.example` - 添加配置示例

### 文档文件
- `P0_OPTIMIZATIONS_APPLIED.md` - 详细实施报告
- `P0_OPTIMIZATIONS_SUMMARY.md` - 快速参考总结

## 注意事项

1. **敏感信息**：确保 `config.env` 已在 `.gitignore` 中（已配置）
2. **日志文件**：确保 `*.log` 已在 `.gitignore` 中（已配置）
3. **测试数据**：确保 `backtest_results/` 已在 `.gitignore` 中（已配置）

## 后续操作

提交后，如果需要推送到远程仓库：

```bash
# 添加远程仓库（如果还没有）
git remote add origin <your-repo-url>

# 推送到远程
git push -u origin main
```
