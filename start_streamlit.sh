#!/bin/bash

# Streamlit 启动脚本
# 用法: ./start_streamlit.sh

echo "🚀 Starting Streamlit Application..."
echo "=================================="

# 检查是否安装了 streamlit
if ! command -v streamlit &> /dev/null
then
    echo "❌ Streamlit is not installed."
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "Please create a .env file with your API keys:"
    echo "  ANTHROPIC_API_KEY=your_key_here"
    echo "  OPENAI_API_KEY=your_key_here"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]
    then
        exit 1
    fi
fi

# 创建必要的目录
mkdir -p data/input data/output data/intermediate

# 启动 Streamlit
echo "✨ Starting Streamlit on http://localhost:8501"
echo "Press Ctrl+C to stop the server"
echo "=================================="

streamlit run streamlit_app.py
