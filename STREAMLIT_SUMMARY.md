# Streamlit 部署版本 - 更新摘要

## ⚙️ 系統需求與相容性

- **Python**: 3.9 或更高版本（建議 3.10+）
- **作業系統**: macOS / Linux / Windows
- **記憶體**: 8GB 以上
- **網路**: 穩定的網際網路連線

### 🔧 Python 3.9 相容性修復

專案已完成 Python 3.9 相容性修復：
- 在 `utils/llm_client.py` 中新增 `from __future__ import annotations`
- 修復 `dict | list` 聯合類型語法錯誤（此語法在 Python 3.10+ 才支援）
- 所有核心模組現已通過 Python 3.9 語法檢查

## 📦 新增檔案

### 核心應用程式
- **streamlit_app.py** - Streamlit Web 應用程式主檔案
  - 完整的 Web UI 介面
  - 支援設定選擇（JRI Aging／Energy）
  - 支援完整流水線與單步執行
  - 即時進度顯示
  - 結果查看與下載
  - 費用報告展示

### 部署相關
- **Dockerfile** - Docker 容器設定
- **docker-compose.yml** - Docker Compose 編排設定
- **.dockerignore** - Docker 建置排除清單
- **.streamlit/config.toml** - Streamlit 設定檔

### 啟動腳本
- **start_streamlit.sh** - 快速啟動腳本（已新增執行權限）

### 文件
- **STREAMLIT_DEPLOY.md** - 完整部署指南（雲端、Docker、Heroku、AWS 等）
- **STREAMLIT_QUICKSTART.md** - 5 分鐘快速啟動指南
- **verify_streamlit.py** - 環境驗證腳本

### 更新檔案
- **requirements.txt** - 新增 streamlit>=1.31.0 依賴
- **README.md** - 更新執行方式與專案結構

---

## 🚀 快速開始

### 方式一：本機執行
```bash
# 1. 安裝依賴套件
pip install -r requirements.txt

# 2. 設定環境變數（若尚未設定）
cp .env.example .env
# 編輯 .env 新增 API 金鑰

# 3. 啟動應用程式
streamlit run streamlit_app.py
# 或
./start_streamlit.sh
```

### 方式二：Docker 部署
```bash
# 1. 確認 .env 檔案存在並包含 API 金鑰

# 2. 啟動容器
docker-compose up -d

# 3. 查看日誌
docker-compose logs -f

# 存取位址: http://localhost:8501
```

### 方式三：驗證環境
```bash
# 執行驗證腳本以檢查所有依賴套件
python3 verify_streamlit.py
```

---

## ✨ 功能特色

### 1. 使用者介面
- **現代化設計**：使用自訂 CSS 美化介面
- **三分頁配置**：
  - 🚀 Run Pipeline - 執行流水線
  - 📊 Results - 查看結果
  - 💰 Cost Report - 費用統計

### 2. 設定管理
- **主題選擇**：JRI Aging Society／Energy Sustainability
- **執行模式**：完整流水線／單步執行
- **進階設定**：
  - 自訂生成數量
  - 啟用／停用翻譯
  - 即時套用設定

### 3. 執行控制
- **即時進度條**：顯示目前執行步驟
- **詳細日誌**：可展開的日誌面板
- **錯誤處理**：友善的錯誤訊息與堆疊追蹤
- **狀態管理**：使用 Session State 保持執行狀態

### 4. 結果展示
- **彙總指標**：顯示各步驟生成的情境數量
- **詳細預覽**：展開查看情境標題與描述
- **檔案下載**：一鍵下載所有 JSON 結果

### 5. 費用追蹤
- **總費用顯示**：精美的指標卡片
- **各步驟明細**：表格呈現每步驟的 Token 使用量與費用
- **報告下載**：匯出完整的 JSON 費用報告

---

## 📋 部署方式比較

| 部署方式 | 難度 | 適用情境 | 優點 | 缺點 |
|---------|------|---------|------|------|
| **本機執行** | ⭐ 簡單 | 開發測試 | 快速啟動，易於偵錯 | 需要本機環境 |
| **Docker** | ⭐⭐ 中等 | 正式環境 | 環境隔離，易於遷移 | 需具備 Docker 知識 |
| **Streamlit Cloud** | ⭐ 簡單 | 快速部署 | 免費托管，自動更新 | 資源有限 |
| **Heroku** | ⭐⭐ 中等 | 小型正式環境 | 部署簡便，可擴充 | 付費服務 |
| **AWS EC2** | ⭐⭐⭐ 複雜 | 大型正式環境 | 完整控制，高效能 | 需具備維運知識 |

---

## 🔍 與 NiceGUI 版本比較

| 特性 | NiceGUI (app.py) | Streamlit (streamlit_app.py) |
|------|------------------|------------------------------|
| **驗證** | ✅ 內建登入 | ❌ 需自行實作 |
| **UI 風格** | 自訂 HTML／CSS | Streamlit 元件 |
| **部署** | 需要伺服器 | 支援雲端免費部署 |
| **開發速度** | 中等 | 快速 |
| **社群支援** | 較小 | 大型社群 |
| **適用情境** | 企業內部系統 | 快速原型、資料應用 |

---

## 🛠️ 自訂指南

### 修改主題顏色
編輯 `.streamlit/config.toml`：
```toml
[theme]
primaryColor = "#667eea"  # 主色調
backgroundColor = "#ffffff"  # 背景色
secondaryBackgroundColor = "#f0f2f6"  # 次要背景
textColor = "#1f2937"  # 文字顏色
```

### 新增設定主題
1. 在 `configs/` 建立新的 `.py` 檔案
2. 在 `streamlit_app.py` 的 `config_options` 字典新增選項：
```python
config_options = {
    "JRI Aging Society": "jri_aging",
    "Energy Sustainability": "energy",
    "Your New Topic": "your_topic_file"  # 新增此行
}
```

### 修改生成數量預設值
在側邊欄的 Advanced Settings 區段修改 `value` 參數：
```python
a1_count = st.number_input("A-1 Scenarios", value=10, ...)
```

---

## 🐛 故障排除

### 問題一：Streamlit 未安裝
```bash
pip install streamlit>=1.31.0
```

### 問題二：連接埠衝突
```bash
streamlit run streamlit_app.py --server.port 8502
```

### 問題三：API 金鑰未設定
```bash
# 檢查 .env 檔案
cat .env

# 或直接設定環境變數
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

### 問題四：Docker 容器無法啟動
```bash
# 查看詳細日誌
docker-compose logs

# 重新建置映像檔
docker-compose build --no-cache
docker-compose up -d
```

### 問題五：記憶體不足
- 減少生成數量（Advanced Settings）
- 改用記憶體較大的伺服器
- 改用單步執行而非完整流水線

---

## 📚 相關文件

1. **STREAMLIT_QUICKSTART.md** - 5 分鐘快速入門
2. **STREAMLIT_DEPLOY.md** - 詳細部署指南（推薦閱讀）
3. **README.md** - 專案總覽
4. **HANDOFF.md** - 工程交接文件
5. **pipeline_flow_document.md** - 流程說明

---

## 🎯 後續建議

### 立即可執行
1. ✅ 執行 `python3 verify_streamlit.py` 驗證環境
2. ✅ 執行 `./start_streamlit.sh` 啟動應用程式
3. ✅ 在瀏覽器中測試基本功能

### 短期優化
- 新增身份驗證（參考 app.py 的 AuthMiddleware）
- 新增使用統計與分析
- 實作結果比較功能
- 新增匯出 Excel 功能

### 長期強化
- 整合資料庫以儲存歷史執行記錄
- 新增多使用者支援
- 實作非同步任務佇列
- 新增即時 WebSocket 通訊
- 整合視覺化圖表（如 D 步驟的矩陣圖）

---

## 📞 支援

如有問題，請：
1. 參閱 STREAMLIT_DEPLOY.md 中的故障排除章節
2. 執行 verify_streamlit.py 診斷問題
3. 查看 pipeline.log 日誌檔案
4. 檢查 Docker 容器日誌（如使用 Docker）

---

**祝部署順利！🎉**

*最後更新：2026-04-28*
