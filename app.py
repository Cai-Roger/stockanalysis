import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

def analyze_stock(stock_symbol, period="6mo"):
    # 1. 下載股市數據
    print(f"正在獲取 {stock_symbol} 的數據...")
    data = yf.download(stock_symbol, period=period)
    
    if data.empty:
        print("找不到該股票代碼，請檢查後再試。")
        return

    # 2. 計算技術指標：移動平均線 (SMA)
    data['MA5'] = data['Close'].rolling(window=5).mean()
    data['MA20'] = data['Close'].rolling(window=20).mean()

    # 3. 簡單策略判斷 (黃金交叉/死亡交叉)
    latest_ma5 = data['MA5'].iloc[-1]
    latest_ma20 = data['MA20'].iloc[-1]
    
    print(f"\n--- {stock_symbol} 分析結果 ---")
    print(f"最新收盤價: {data['Close'].iloc[-1]:.2f}")
    print(f"5日均線: {latest_ma5:.2f}")
    print(f"20日均線: {latest_ma20:.2f}")

    if latest_ma5 > latest_ma20:
        print("趨勢提示：目前 5MA > 20MA，呈現偏多排列。")
    else:
        print("趨勢提示：目前 5MA < 20MA，呈現偏空排列。")

    # 4. 繪製圖表
    plt.figure(figsize=(12, 6))
    plt.plot(data['Close'], label='Close Price', color='black', alpha=0.5)
    plt.plot(data['MA5'], label='5-Day MA', color='blue')
    plt.plot(data['MA20'], label='20-Day MA', color='red')
    plt.title(f'Stock Price Analysis: {stock_symbol}')
    plt.xlabel('Date')
    plt.ylabel('Price')
    plt.legend()
    plt.grid(True)
    plt.show()

# 執行分析：台股請加 .TW (例如 2330.TW)，美股直接輸入代號 (例如 AAPL)
analyze_stock("2330.TW")
