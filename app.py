import yfinance as yf

def get_stock_price(symbol):
    try:
        # 建立股票物件
        stock = yf.Ticker(symbol)
        
        # 獲取即時行情資訊
        # fast_info 提供當前市價、漲跌幅等基礎資訊
        info = stock.fast_info
        
        current_price = info['last_price']
        currency = info['currency']
        
        # 獲取公司名稱（選用）
        company_name = stock.info.get('longName', '未知公司')

        print(f"--- 查詢結果 ---")
        print(f"公司名稱: {company_name}")
        print(f"股票代號: {symbol.upper()}")
        print(f"當前股價: {current_price:.2f} {currency}")
        print(f"----------------")
        
    except Exception as e:
        print(f"錯誤：找不到股票代號 '{symbol}' 或網路連線異常。")
        print(f"提示：台股請輸入代碼+ .TW，例如 '2330.TW'")

if __name__ == "__main__":
    while True:
        target = input("\n請輸入股票代號 (輸入 'q' 離開): ").strip()
        if target.lower() == 'q':
            break
        get_stock_price(target)
