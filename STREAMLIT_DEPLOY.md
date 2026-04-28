# Streamlit 部署指南

## 系統需求

- **Python**: 3.9 或更高版本（建議 3.10+）
- **作業系統**: macOS / Linux / Windows
- **記憶體**: 8GB 以上
- **網路**: 穩定的網際網路連線（用於 API 呼叫）

## 快速開始

### 1. 檢查 Python 版本

```bash
python3 --version  # 應該是 3.9 或更高
```

### 2. 安裝依賴套件

```bash
pip install -r requirements.txt
```

### 3. 設定環境變數

建立 `.env` 檔案並設定 API 金鑰：

```bash
ANTHROPIC_API_KEY=your_claude_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

### 4. 啟動應用程式

```bash
streamlit run streamlit_app.py
```

或使用啟動腳本：

```bash
./start_streamlit.sh
```

應用程式將在瀏覽器中自動開啟，預設位址：`http://localhost:8501`

---

## 功能特色

### 🔮 主要功能

1. **設定選擇**
   - JRI Aging Society（高齡化社會）
   - Energy Sustainability（能源永續性）

2. **執行模式**
   - 完整流水線：A→B→C→D 四個步驟依序執行
   - 單步執行：僅執行指定的單一步驟

3. **進階設定**
   - 自訂生成數量
   - 啟用／停用日譯中翻譯
   - 即時調整設定

4. **結果展示**
   - 即時進度顯示
   - 分步驟結果預覽
   - JSON 檔案下載

5. **費用報告**
   - 總費用統計
   - API 呼叫次數
   - Token 使用量
   - 各步驟費用明細

---

## 部署至雲端

### Streamlit Cloud（推薦）

1. **準備 GitHub 儲存庫**
   ```bash
   git add .
   git commit -m "Add Streamlit deployment"
   git push origin main
   ```

2. **部署至 Streamlit Cloud**
   - 前往 [share.streamlit.io](https://share.streamlit.io/)
   - 登入 GitHub 帳號
   - 選擇儲存庫與分支
   - 設定主檔案：`streamlit_app.py`
   - 在 Advanced settings 中新增環境變數：
     - `ANTHROPIC_API_KEY`
     - `OPENAI_API_KEY`

3. **點擊 Deploy**

### 其他雲端平台

#### Heroku

1. 建立 `Procfile`：
```
web: sh setup.sh && streamlit run streamlit_app.py
```

2. 建立 `setup.sh`：
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

3. 部署：
```bash
heroku create your-app-name
heroku config:set ANTHROPIC_API_KEY=your_key
heroku config:set OPENAI_API_KEY=your_key
git push heroku main
```

#### AWS EC2

```bash
# SSH 連線至 EC2 執行個體
ssh -i your-key.pem ubuntu@your-ec2-ip

# 安裝 Python 與依賴套件
sudo apt update
sudo apt install python3-pip
git clone your-repo
cd your-repo
pip3 install -r requirements.txt

# 設定環境變數
export ANTHROPIC_API_KEY=your_key
export OPENAI_API_KEY=your_key

# 執行應用程式（背景執行）
nohup streamlit run streamlit_app.py --server.port 8501 &
```

#### Docker

1. 建立 `Dockerfile`：
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

2. 建置與執行：
```bash
docker build -t scenario-pipeline .
docker run -p 8501:8501 \
  -e ANTHROPIC_API_KEY=your_key \
  -e OPENAI_API_KEY=your_key \
  scenario-pipeline
```

---

## 設定說明

### Streamlit 設定

建立 `.streamlit/config.toml` 以自訂設定：

```toml
[theme]
primaryColor = "#667eea"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#1f2937"
font = "sans serif"

[server]
port = 8501
headless = true
enableCORS = false
maxUploadSize = 200

[browser]
gatherUsageStats = false
```

### 環境變數

| 變數名稱 | 說明 | 必填 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Claude API 金鑰 | ✅ |
| `OPENAI_API_KEY` | OpenAI API 金鑰 | ✅ |

---

## 使用指南

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

#### 自訂參數

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

#### 單步偵錯

1. 在側邊欄選擇「Single Step」
2. 選擇要執行的步驟
3. 點擊執行
4. 查看該步驟的詳細輸出與日誌

---

## 故障排除

### 常見問題

1. **Python 版本錯誤**
   ```
   TypeError: unsupported operand type(s) for |: 'type' and 'type'
   ```
   解決方式：確認 Python 版本至少為 3.9
   ```bash
   python3 --version
   # 如果版本過舊，請升級 Python
   ```

2. **API 金鑰錯誤**
   ```
   Error: API key not set
   ```
   解決方式：確認 `.env` 檔案是否已正確設定

3. **記憶體不足**
   ```
   MemoryError
   ```
   解決方式：減少生成數量，或改用記憶體較大的伺服器

4. **連接埠被佔用**
   ```
   Port 8501 is already in use
   ```
   解決方式：
   ```bash
   streamlit run streamlit_app.py --server.port 8502
   ```

5. **依賴套件安裝失敗**
   ```bash
   # 使用虛擬環境
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

### 查看日誌

- 應用程式日誌：`pipeline.log`
- Streamlit 日誌：主控台輸出

---

## 效能最佳化

### 建議規格

- **CPU**：4 核心以上
- **記憶體**：8GB 以上
- **網路**：穩定的網際網路連線（API 呼叫所需）

### 最佳化技巧

1. **減少生成數量**：測試時使用較小的數值
2. **停用翻譯**：若不需要中文輸出
3. **使用較快的模型**：在設定中選擇 `haiku` 或 `sonnet`
4. **快取結果**：利用檢查點機制避免重複計算

---

## 安全注意事項

1. **保護 API 金鑰**
   - 請勿將 `.env` 檔案提交至 Git
   - 使用環境變數或金鑰管理服務

2. **存取控制**
   - 在正式環境中加入身份驗證
   - 使用防火牆限制存取

3. **資料隱私**
   - 確保輸入資料不含敏感資訊
   - 定期清理輸出目錄

---

## 更新與維護

### 更新應用程式

```bash
git pull origin main
pip install -r requirements.txt --upgrade
streamlit run streamlit_app.py
```

### 備份資料

```bash
# 備份輸出與中間資料
tar -czf backup_$(date +%Y%m%d).tar.gz data/
```

---

## 支援

如有問題或建議，請參閱：
- 專案 README.md
- HANDOFF.md（開發文件）
- pipeline_flow_document.md（流程說明）

---

**祝您使用 Streamlit 部署版本愉快！🚀**
