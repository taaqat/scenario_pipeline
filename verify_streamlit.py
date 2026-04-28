#!/usr/bin/env python3
"""
Streamlit 应用验证脚本
检查 Streamlit 应用是否能正常加载（不实际运行 pipeline）
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def check_imports():
    """检查所有必需的导入"""
    print("🔍 检查依赖导入...")
    
    missing = []
    
    try:
        import streamlit
        print(f"✅ Streamlit {streamlit.__version__}")
    except ImportError:
        print("❌ Streamlit 未安装")
        missing.append("streamlit")
    
    try:
        import pandas
        print(f"✅ Pandas {pandas.__version__}")
    except ImportError:
        print("❌ Pandas 未安装")
        missing.append("pandas")
    
    try:
        import anthropic
        print(f"✅ Anthropic SDK")
    except ImportError:
        print("❌ Anthropic SDK 未安装")
        missing.append("anthropic")
    
    try:
        import openai
        print(f"✅ OpenAI SDK")
    except ImportError:
        print("❌ OpenAI SDK 未安装")
        missing.append("openai")
    
    try:
        import config
        print(f"✅ Config module")
    except ImportError as e:
        print(f"❌ Config module 导入失败: {e}")
        missing.append("config")
    
    return missing


def check_files():
    """检查必需文件是否存在"""
    print("\n📁 检查必需文件...")
    
    required_files = [
        "streamlit_app.py",
        "config.py",
        "requirements.txt",
        ".streamlit/config.toml",
    ]
    
    missing = []
    for file in required_files:
        path = Path(file)
        if path.exists():
            print(f"✅ {file}")
        else:
            print(f"❌ {file} 不存在")
            missing.append(file)
    
    return missing


def check_directories():
    """检查数据目录"""
    print("\n📂 检查数据目录...")
    
    dirs = ["data/input", "data/output", "data/intermediate"]
    for d in dirs:
        path = Path(d)
        if path.exists():
            print(f"✅ {d}")
        else:
            print(f"⚠️  {d} 不存在（将自动创建）")


def check_env():
    """检查环境变量"""
    print("\n🔑 检查环境变量...")
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    api_keys = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    }
    
    for key, value in api_keys.items():
        if value:
            print(f"✅ {key} 已设置")
        else:
            print(f"⚠️  {key} 未设置")


def main():
    print("=" * 60)
    print("🔮 Streamlit 应用验证")
    print("=" * 60)
    print()
    
    missing_imports = check_imports()
    missing_files = check_files()
    check_directories()
    check_env()
    
    print("\n" + "=" * 60)
    print("📊 验证总结")
    print("=" * 60)
    
    if missing_imports:
        print(f"\n❌ 缺少依赖: {', '.join(missing_imports)}")
        print("   运行: pip install -r requirements.txt")
    
    if missing_files:
        print(f"\n❌ 缺少文件: {', '.join(missing_files)}")
    
    if not missing_imports and not missing_files:
        print("\n✅ 所有检查通过！")
        print("\n🚀 启动 Streamlit 应用:")
        print("   streamlit run streamlit_app.py")
        print("   或")
        print("   ./start_streamlit.sh")
    else:
        print("\n⚠️  请解决上述问题后再启动应用")
    
    print()


if __name__ == "__main__":
    main()
