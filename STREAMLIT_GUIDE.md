# Streamlit Web 應用程式完整指南

> AI Scenario Pipeline - Streamlit 部署版本

## 📋 目錄

- [快速開始](#-快速開始-5-分鐘)
- [系統需求](#-系統需求)
- [功能特色](#-功能特色)
- [配置系統](#-配置系統)
- [部署方式](#-部署方式)
- [使用指南](#-使用指南)
- [故障排除](#-故障排除)
- [效能優化](#-效能優化)
- [安全注意事項](#-安全注意事項)
- [版本比較](#-版本比較)
- [更新與維護](#-更新與維護)

---

## 🚀 快速開始（5 分鐘）

### 方法一：本機執行（推薦用於開發）

```bash
# 1. 檢查 Python 版本（需要 3.9+）
python3 --version

# 2. 安裝依賴套件
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env 填入你的 API 金鑰

# 4. 啟動應用程式
streamlit run streamlit_app.py
# 或使用啟動腳本
./start_streamlit.sh
```

瀏覽器將自動開啟 http://localhost:8501

### 方法二：Docker 部署（推薦用於正式環境）

```bash
# 1. 建立 .env 檔案
cat > .env << EOF
ANTHROPIC_API_KEY=your-claude-api-key
OPENAI_API_KEY=your-openai-api-key
EOF

# 2. 啟動容器
docker-compose up -d

# 3. 查看日誌
docker-compose logs -f

# 存取位址: http://localhost:8501
```

停止服務：
```bash
docker-compose down
```

### 方法三：Streamlit Cloud（最快速的雲端部署）

1. **推送至 GitHub**
   ```bash
   git add .
   git commit -m "Add Streamlit app"
   git push
   ```

2. **前往 [share.streamlit.io](https://share.streamlit.io/)**

3. **連結儲存庫並部署**
   - 選擇儲存庫與分支
   - 主檔案：`streamlit_app.py`
   - 在 Advanced settings 新增 Secrets：
     ```toml
     ANTHROPIC_API_KEY = "your-key"
     OPENAI_API_KEY = "your-key"
     ```

4. **點擊 Deploy** ✨

---

## ⚙️ 系統需求

### 基本需求

- **Python**: 3.9 或更高版本（建議 3.10+）
- **作業系統**: macOS / Linux / Windows
- **記憶體**: 8GB 以上
- **網路**: 穩定的網際網路連線（用於 API 呼叫）

### Python 3.9 相容性

專案已完成 Python 3.9 相容性修復：
- 在 `utils/llm_client.py` 中新增 `from __future__ import annotations`
- 修復 `dict | list` 聯合類型語法錯誤
- 所有核心模組現已通過 Python 3.9 語法檢查

### 效能建議

- **CPU**: 4 核心以上
- **記憶體**: 8GB 以上（建議 16GB）
- **網路頻寬**: 穩定連線（API 呼叫密集）

---

## ✨ 功能特色

### 1. 使用者介面

- **現代化設計**：使用自訂 CSS 美化介面
- **三分頁配置**：
  - 🚀 **Run Pipeline** - 執行流水線
  - 📊 **Results** - 查看結果
  - 💰 **Cost Report** - 費用統計

### 2. 主要功能

#### 設定選擇
- **JRI Aging Society**（高齡化社會）
- **Energy Sustainability**（能源永續性）

#### 執行模式
- **完整流水線**：A→B→C→D 四個步驟依序執行
- **單步執行**：僅執行指定的單一步驟（適用於偵錯或重新生成）

#### 進階設定
- 自訂各步驟生成數量
- 啟用／停用日譯中翻譯
- 即時調整設定

#### 結果展示
- 即時進度顯示
- 分步驟結果預覽
- JSON 檔案下載
- 彙總指標展示

#### 費用報告
- 總費用統計
- API 呼叫次數
- Token 使用量
- 各步驟費用明細

### 3. 技術特色

- **狀態管理**：使用 Streamlit Session State 保持執行狀態
- **錯誤處理**：友善的錯誤訊息與堆疊追蹤
- **詳細日誌**：可展開的日誌面板
- **即時進度條**：顯示目前執行步驟

---

## 🔧 配置系統

### 配置方式（優先級從低到高）

Streamlit 提供四種配置方式，後者會覆蓋前者：

1. **全域配置檔** - `~/.streamlit/config.toml`（macOS/Linux）
2. **項目配置檔** - `.streamlit/config.toml`（本專案使用 ✓）
3. **環境變數** - `STREAMLIT_*` 前綴
4. **命令列參數** - 執行時指定（最高優先級）

### 項目配置檔

本專案已包含 `.streamlit/config.toml`：

```toml
[theme]
primaryColor = "#667eea"              # 主題色
backgroundColor = "#ffffff"            # 背景色
secondaryBackgroundColor = "#f0f2f6"  # 次要背景色
textColor = "#1f2937"                  # 文字顏色
font = "sans serif"                    # 字型

[server]
port = 8501                            # 服務端口
headless = true                        # 無頭模式（不自動開啟瀏覽器）
enableCORS = false                     # 跨域請求（本地開發建議 false）
maxUploadSize = 200                    # 最大上傳檔案大小（MB）

[browser]
gatherUsageStats = false               # 停用遙測數據收集
serverAddress = "localhost"            # 伺服器地址
```

### 環境變數配置

環境變數命名規則：
- 加上 `STREAMLIT_` 前綴
- 將配置項轉換為大寫蛇形命名（UPPER_SNAKE_CASE）
- 包含配置段落（section）作為前綴

#### API 金鑰（必填）

| 變數名稱 | 說明 | 必填 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Claude API 金鑰 | ✅ |
| `OPENAI_API_KEY` | OpenAI API 金鑰 | ✅ |

#### Streamlit 配置（選填）

```bash
# API 金鑰（必填）
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"

# Streamlit 配置（選填，會覆蓋 config.toml）
export STREAMLIT_SERVER_PORT=8501
export STREAMLIT_SERVER_ADDRESS=0.0.0.0
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=true
```

**配置對應關係**：
- `STREAMLIT_SERVER_PORT` ⟷ `[server] port`
- `STREAMLIT_SERVER_ADDRESS` ⟷ `[server] address`
- `STREAMLIT_BROWSER_GATHER_USAGE_STATS` ⟷ `[browser] gatherUsageStats`
- `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS` ⟷ `[client] showErrorDetails`

### 命令列參數

命令列參數使用點號（.）分隔配置段落和選項：

```bash
# 自訂端口
streamlit run streamlit_app.py --server.port 8502

# 允許跨域請求（生產環境）
streamlit run streamlit_app.py --server.enableCORS true

# 設定綁定地址
streamlit run streamlit_app.py --server.address 0.0.0.0

# 多個參數組合
streamlit run streamlit_app.py \
  --server.port 8502 \
  --server.address 0.0.0.0 \
  --server.enableCORS true

# 查看所有可用配置
streamlit config show
```

### Docker 環境變數配置

在 `docker-compose.yml` 中配置：

```yaml
environment:
  # API 金鑰
  - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
  - OPENAI_API_KEY=${OPENAI_API_KEY}
  # Streamlit 配置（選填，會覆蓋 config.toml）
  - STREAMLIT_SERVER_PORT=8501
  - STREAMLIT_SERVER_ADDRESS=0.0.0.0
  - STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
```

### 配置生效時機

| 配置類型 | 生效時機 | 操作 |
|---------|----------|------|
| 主題設定（theme） | 立即生效 | 無需重啟 |
| 伺服器設定（server） | 需要重啟 | Ctrl+C 後重新啟動 |
| 瀏覽器設定（browser） | 需要重啟 | Ctrl+C 後重新啟動 |

---

## 🌐 部署方式

### 部署方式比較

| 部署方式 | 難度 | 適用情境 | 優點 | 缺點 |
|---------|------|---------|------|------|
| **本機執行** | ⭐ 簡單 | 開發測試 | 快速啟動，易於偵錯 | 需要本機環境 |
| **Docker** | ⭐⭐ 中等 | 正式環境 | 環境隔離，易於遷移 | 需具備 Docker 知識 |
| **Streamlit Cloud** | ⭐ 簡單 | 快速部署 | 免費托管，自動更新 | 資源有限 |
| **Heroku** | ⭐⭐ 中等 | 小型正式環境 | 部署簡便，可擴充 | 付費服務 |
| **AWS EC2** | ⭐⭐⭐ 複雜 | 大型正式環境 | 完整控制，高效能 | 需具備維運知識 |

### Docker 部署（詳細步驟）

本專案已包含完整的 Docker 配置：

**1. 檔案結構**
```
scenario_pipeline/
├── Dockerfile           # Docker 映像檔配置
├── docker-compose.yml   # Docker Compose 編排
├── .dockerignore        # 排除清單
└── .env                 # 環境變數（需自行建立）
```

**2. 部署步驟**
```bash
# 確認 Docker 已安裝
docker --version
docker-compose --version

# 建立 .env 檔案
cat > .env << EOF
ANTHROPIC_API_KEY=your-claude-api-key
OPENAI_API_KEY=your-openai-api-key
EOF

# 啟動服務
docker-compose up -d

# 查看日誌
docker-compose logs -f streamlit

# 停止服務
docker-compose down
```

**3. 自訂 Docker 設定**

編輯 `docker-compose.yml`：
```yaml
services:
  streamlit:
    build: .
    container_name: scenario-pipeline-streamlit
    ports:
      - "8501:8501"  # 修改端口：外部:內部
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - STREAMLIT_SERVER_PORT=8501
    volumes:
      - ./data:/app/data
      - ./configs:/app/configs
    restart: unless-stopped
```

### Streamlit Cloud 部署

**優點**：
- 完全免費（社群版）
- 自動部署（Git Push 即更新）
- 內建 SSL 憑證
- 無需維護伺服器

**步驟**：

1. **準備 GitHub 儲存庫**
   ```bash
   git add .
   git commit -m "Add Streamlit deployment"
   git push origin main
   ```

2. **登入 Streamlit Cloud**
   - 前往 [share.streamlit.io](https://share.streamlit.io/)
   - 使用 GitHub 帳號登入

3. **新增應用程式**
   - 點擊「New app」
   - 選擇儲存庫：`your-username/scenario_pipeline`
   - Branch：`main`
   - Main file path：`streamlit_app.py`

4. **設定 Secrets**
   - 點擊「Advanced settings」
   - 在 Secrets 區塊加入：
     ```toml
     ANTHROPIC_API_KEY = "your-claude-api-key"
     OPENAI_API_KEY = "your-openai-api-key"
     ```

5. **部署**
   - 點擊「Deploy!」
   - 等待約 3-5 分鐘完成部署

### Heroku 部署

**1. 建立必要檔案**

`Procfile`：
```
web: sh setup.sh && streamlit run streamlit_app.py
```

`setup.sh`：
```bash
mkdir -p ~/.streamlit/
echo "\
[server]\n\
headless = true\n\
port = $PORT\n\
enableCORS = false\n\
\n\
" > ~/.streamlit/config.toml
```

**2. 部署至 Heroku**
```bash
# 安裝 Heroku CLI
brew install heroku/brew/heroku  # macOS
# 或前往 https://devcenter.heroku.com/articles/heroku-cli 下載

# 登入
heroku login

# 建立應用程式
heroku create your-app-name

# 設定環境變數
heroku config:set ANTHROPIC_API_KEY=your_key
heroku config:set OPENAI_API_KEY=your_key

# 部署
git push heroku main

# 開啟應用程式
heroku open
```

### AWS EC2 部署

**1. 啟動 EC2 執行個體**
- 選擇 Ubuntu 22.04 LTS
- 類型：t3.medium 或更高
- 開放安全群組：Port 8501

**2. SSH 連線並設定**
```bash
# 連線至 EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# 安裝依賴
sudo apt update
sudo apt install python3-pip git -y

# 下載專案
git clone https://github.com/your-username/scenario_pipeline.git
cd scenario_pipeline

# 安裝套件
pip3 install -r requirements.txt

# 設定環境變數
export ANTHROPIC_API_KEY=your_key
export OPENAI_API_KEY=your_key

# 背景執行
nohup streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0 &

# 查看日誌
tail -f nohup.out
```

**3. 使用 systemd 管理服務**

建立 `/etc/systemd/system/streamlit.service`：
```ini
[Unit]
Description=Streamlit Scenario Pipeline
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/scenario_pipeline
Environment="ANTHROPIC_API_KEY=your_key"
Environment="OPENAI_API_KEY=your_key"
ExecStart=/usr/local/bin/streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

啟動服務：
```bash
sudo systemctl daemon-reload
sudo systemctl enable streamlit
sudo systemctl start streamlit
sudo systemctl status streamlit
```

---

## 📖 使用指南

### 基本流程

1. **選擇主題設定**
   - 在側邊欄選擇「JRI Aging Society」或「Energy Sustainability」

2. **選擇執行模式**
   - 完整流水線：依序執行所有步驟
   - 單步執行：僅執行特定步驟（適用於偵錯或重新生成）

3. **調整進階設定**（選填）
   - 修改各步驟的生成數量
   - 啟用翻譯功能

4. **執行流水線**
   - 點擊「▶️ Run Pipeline」按鈕
   - 觀察即時進度與日誌

5. **查看結果**
   - 切換至「Results」分頁查看生成的情境
   - 下載 JSON 結果檔案

6. **檢查費用**
   - 切換至「Cost Report」分頁
   - 查看詳細的 API 使用與費用統計

### 進階用法

#### 單步偵錯

1. 在側邊欄選擇「Single Step」
2. 選擇要執行的步驟（A-1, B, C, D）
3. 點擊執行
4. 查看該步驟的詳細輸出與日誌

#### 自訂參數（程式碼層級）

```python
# 在程式碼中使用 apply_overrides
from config import apply_overrides

apply_overrides({
    "A1_GENERATE_N": 20,
    "B_TOP_N": 3000,
    "MODEL_HEAVY": "claude-opus-4-6",
    "TRANSLATE_ENABLED": True
})
```

#### 修改主題顏色

編輯 `.streamlit/config.toml`：
```toml
[theme]
primaryColor = "#667eea"  # 修改為你喜歡的顏色
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#1f2937"
```

儲存後重新整理瀏覽器即可看到變更。

#### 新增設定主題

1. 在 `configs/` 建立新的 `.py` 檔案（例如 `my_topic.py`）
2. 在 `streamlit_app.py` 的 `config_options` 字典新增選項：
```python
config_options = {
    "JRI Aging Society": "jri_aging",
    "Energy Sustainability": "energy",
    "My Custom Topic": "my_topic"  # 新增此行
}
```

---

## 🔧 故障排除

### 常見問題

#### 1. Python 版本錯誤
```
TypeError: unsupported operand type(s) for |: 'type' and 'type'
```

**解決方式**：
```bash
python3 --version  # 確認版本至少為 3.9
# 如果版本過舊，請升級 Python
```

#### 2. 啟動失敗，提示缺少依賴套件
```bash
pip install -r requirements.txt

# 或使用虛擬環境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### 3. API 金鑰錯誤
```
Error: API key not set
```

**解決方式**：
```bash
# 檢查 .env 檔案
cat .env

# 或直接設定環境變數
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

#### 4. 連接埠被佔用
```
Port 8501 is already in use
```

**解決方式**：
```bash
# 使用不同端口
streamlit run streamlit_app.py --server.port 8502

# 或終止佔用的程序
lsof -ti:8501 | xargs kill -9  # macOS/Linux
```

#### 5. Docker 容器無法啟動

**解決方式**：
```bash
# 查看日誌
docker-compose logs streamlit

# 重新建置
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# 檢查 .env 檔案是否存在
ls -la .env
```

#### 6. 記憶體不足
```
MemoryError
```

**解決方式**：
- 減少生成數量（在 Advanced Settings 調整）
- 使用記憶體較大的伺服器
- 啟用單步執行模式

#### 7. 配置檔修改後沒有生效

**解決方式**：
- **主題設定**：重新整理瀏覽器即可
- **非主題設定**：使用 Ctrl+C 停止應用程式，然後重新啟動

#### 8. 如何查看所有可用配置選項

```bash
streamlit config show
```

### 查看日誌

- **應用程式日誌**：`pipeline.log`
- **Streamlit 日誌**：主控台輸出
- **Docker 日誌**：`docker-compose logs -f streamlit`

---

## ⚡ 效能優化

### 最佳化技巧

1. **減少生成數量**
   - 測試時使用較小的數值
   - 在 Advanced Settings 調整各步驟的生成數量

2. **停用翻譯**
   - 若不需要中文輸出，取消勾選「Enable Translation」
   - 可節省約 30% 的 API 呼叫

3. **使用較快的模型**
   - 在 `config.py` 中修改模型設定
   - 開發測試：使用 `haiku`
   - 正式生成：使用 `sonnet` 或 `opus`

4. **快取結果**
   - 利用檢查點機制避免重複計算
   - 檢查點檔案保存於 `data/intermediate/`

5. **平行執行（未來功能）**
   - 目前步驟為序列執行
   - 未來版本考慮部分步驟平行化

### 資源監控

```bash
# 監控 CPU 和記憶體使用
top  # Linux/macOS
htop  # 需安裝

# Docker 資源使用
docker stats
```

---

## 🔒 安全注意事項

### 1. 保護 API 金鑰

- ❌ **絕對不要**將 `.env` 檔案提交至 Git
- ✅ 確認 `.env` 已加入 `.gitignore`
- ✅ 使用環境變數或金鑰管理服務（如 AWS Secrets Manager）
- ✅ 定期輪換 API 金鑰

### 2. 存取控制

- 在正式環境中加入身份驗證（Streamlit 社群版無內建認證）
- 使用防火牆限制存取來源
- 考慮使用反向代理（如 Nginx）加入 SSL 和基本認證

### 3. 資料隱私

- 確保輸入資料不含敏感資訊
- 定期清理 `data/output/` 目錄
- 避免在日誌中輸出敏感資料

### 4. 網路安全

- 生產環境建議啟用 HTTPS
- 設定 `enableCORS` 根據需求調整
- 使用環境變數而非硬編碼敏感資訊

---

## 🔄 更新與維護

### 更新應用程式

```bash
# 從 Git 拉取最新程式碼
git pull origin main

# 更新依賴套件
pip install -r requirements.txt --upgrade

# 重新啟動應用程式
streamlit run streamlit_app.py

# Docker 環境
docker-compose down
docker-compose pull
docker-compose up -d --build
```

### 備份資料

```bash
# 備份輸出與中間資料
tar -czf backup_$(date +%Y%m%d).tar.gz data/

# 備份至遠端（使用 AWS S3 範例）
aws s3 cp backup_$(date +%Y%m%d).tar.gz s3://your-bucket/backups/
```

### 清理舊資料

```bash
# 清理超過 30 天的輸出資料
find data/output -type f -mtime +30 -delete

# 清理中間檔案
rm -rf data/intermediate/*
```

### 監控與日誌

```bash
# 查看應用程式日誌
tail -f pipeline.log

# 查看 Streamlit 日誌
streamlit run streamlit_app.py 2>&1 | tee streamlit.log

# Docker 日誌
docker-compose logs -f --tail=100 streamlit
```

---

## 📚 相關文件

- **README.md** - 專案總覽
- **HANDOFF.md** - 開發移交文件
- **pipeline_flow_document.md** - 流程說明
- **.streamlit/config.toml** - Streamlit 配置檔

---

## 🙋 支援與協助

### 環境驗證

執行驗證腳本以檢查所有依賴套件：

```bash
python3 verify_streamlit.py
```

### 獲取協助

如有問題或建議，請：

1. 檢查本文件的「故障排除」章節
2. 查看 `pipeline.log` 日誌檔案
3. 參考 Streamlit 官方文件：https://docs.streamlit.io
4. 提交 Issue 至專案儲存庫

---

## 📦 專案檔案結構

```
scenario_pipeline/
├── streamlit_app.py          # Streamlit 主應用程式
├── start_streamlit.sh        # 快速啟動腳本
├── verify_streamlit.py       # 環境驗證腳本
├── Dockerfile                # Docker 映像檔配置
├── docker-compose.yml        # Docker Compose 編排
├── .dockerignore             # Docker 建置排除清單
├── .streamlit/
│   └── config.toml          # Streamlit 配置檔
├── .env.example             # 環境變數範例
├── requirements.txt          # Python 依賴套件
├── config.py                # 專案配置
├── steps/                   # 流水線步驟
│   ├── step_a1.py
│   ├── step_b.py
│   ├── step_c.py
│   └── step_d.py
├── utils/                   # 工具模組
├── configs/                 # 主題配置
│   ├── jri_aging.py
│   └── energy.py
├── prompts/                 # LLM 提示詞
├── data/                    # 資料目錄
│   ├── input/
│   ├── intermediate/
│   └── output/
└── STREAMLIT_GUIDE.md       # 本文件
```

---

## 💡 使用提示

- **首次執行建議**：先執行單一步驟測試，確認設定正確無誤
- **費用控制**：測試時請減少生成數量（Advanced Settings）
- **效能最佳化**：使用 Docker 部署可獲得更穩定的效能
- **資料備份**：定期備份 `data/output/` 目錄
- **日誌查看**：執行時注意查看日誌，及早發現問題

---

**祝您使用 Streamlit 版本愉快！🚀**

*最後更新：2026年4月28日*
