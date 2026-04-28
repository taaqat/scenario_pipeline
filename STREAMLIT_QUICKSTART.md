# Streamlit 快速啟動指南

## ⚙️ 系統需求

- **Python**: 3.9 或更高版本
- **作業系統**: macOS / Linux / Windows
- **記憶體**: 建議 8GB 以上

## 🚀 5 分鐘快速啟動

### 方法一：本機執行（推薦用於開發）

```bash
# 0. 檢查 Python 版本（需要 3.9+）
python3 --version

# 1. 安裝依賴套件
pip install streamlit

# 2. 設定環境變數
export ANTHROPIC_API_KEY="your-claude-api-key"
export OPENAI_API_KEY="your-openai-api-key"

# 3. 啟動
streamlit run streamlit_app.py
```

瀏覽器將自動開啟 http://localhost:8501

---

### 方法二：使用啟動腳本

```bash
chmod +x start_streamlit.sh
./start_streamlit.sh
```

---

### 方法三：Docker 部署（推薦用於正式環境）

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

---

### 方法四：雲端部署（Streamlit Cloud）

1. **將程式碼推送至 GitHub**
   ```bash
   git add .
   git commit -m "Add Streamlit app"
   git push
   ```

2. **前往 [share.streamlit.io](https://share.streamlit.io/)**

3. **連結 GitHub 儲存庫並部署**
   - 選擇儲存庫與分支
   - 主檔案：`streamlit_app.py`
   - 在 Advanced settings 新增 Secrets：
     ```toml
     ANTHROPIC_API_KEY = "your-key"
     OPENAI_API_KEY = "your-key"
     ```

4. **點擊 Deploy** ✨

---

## 📋 使用步驟

1. **選擇主題**
   - 側邊欄選擇「JRI Aging Society」或「Energy Sustainability」

2. **選擇執行模式**
   - 完整流水線：A→B→C→D
   - 單步執行：選擇特定步驟

3. **執行**
   - 點擊「▶️ Run Pipeline」
   - 等待完成（可能需要 10～30 分鐘）

4. **查看結果**
   - Results 分頁：查看生成的情境
   - Cost Report 分頁：查看 API 使用費用
   - 下載 JSON 檔案

---

## 🔧 常見問題

### Q：啟動失敗，提示缺少依賴套件？
```bash
pip install -r requirements.txt
```

### Q：API 金鑰錯誤？
請確認 `.env` 檔案或環境變數是否已正確設定。

### Q：連接埠被佔用？
```bash
streamlit run streamlit_app.py --server.port 8502
```

### Q：Docker 容器無法啟動？
```bash
# 查看日誌
docker-compose logs

# 重新建置
docker-compose build --no-cache
docker-compose up -d
```

---

## 📖 詳細文件

完整部署指南請參考：[STREAMLIT_DEPLOY.md](STREAMLIT_DEPLOY.md)

---

## 💡 使用提示

- **首次執行建議**：先執行單一步驟測試，確認設定正確無誤
- **費用控制**：測試時請減少生成數量（Advanced Settings）
- **效能最佳化**：使用 Docker 部署可獲得更穩定的效能
- **資料備份**：定期備份 `data/output/` 目錄

---

祝使用愉快！🎉
