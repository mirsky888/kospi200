import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import websocket
import json
import threading
import time

# -----------------------------------------------------------------------------
# 1. 페이지 및 자동 리프레시 설정 (1초마다 화면 갱신)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="산강식 실시간 선물/지수 분석 시스템",
    page_icon="📈",
    layout="wide"
)

# 1000ms(1초) 마다 스트리밋 화면 자동 재실행
st_autorefresh(interval=1000, key="realtime_tick")

st.title("⚡ 실시간 선물/지수 차트 및 산강식 지표 분석")

# -----------------------------------------------------------------------------
# 2. 세션 상태(Session State) 데이터 저장소 초기화
# -----------------------------------------------------------------------------
if "price_data" not in st.session_state:
    st.session_state["price_data"] = pd.DataFrame(columns=["Timestamp", "Price"])

if "ws_connected" not in st.session_state:
    st.session_state["ws_connected"] = False

# -----------------------------------------------------------------------------
# 3. 사이드바 설정 (API 키 및 연동 옵션)
# -----------------------------------------------------------------------------
st.sidebar.header("🔑 연동 및 차트 설정")
symbol = st.sidebar.text_input("종목 코드 (예: KOSPI200 / BTC)", "BTC")

st.sidebar.subheader("API 정보 (필요시 입력)")
app_key = st.sidebar.text_input("App Key", type="password")
app_secret = st.sidebar.text_input("App Secret", type="password")

# -----------------------------------------------------------------------------
# 4. 실시간 웹소켓(WebSocket) 수신 스레드
# -----------------------------------------------------------------------------
def run_websocket():
    """
    실시간 체결가를 수신하는 웹소켓 클라이언트 예시 함수입니다.
    선택하신 증권사/거래소 웹소켓 규격에 맞게 파싱 로직을 커스텀할 수 있습니다.
    """
    # 예시: public 웹소켓 엔드포인트 연동
    ws_url = "wss://pubwss.bithumb.com/pub/ws"
    
    def on_message(ws, message):
        try:
            data = json.loads(message)
            if "content" in data and "tickPrice" in data["content"]:
                price = float(data["content"]["tickPrice"])
                now = pd.Timestamp.now()
                
                # 데이터 프레임 추가
                new_row = pd.DataFrame([{"Timestamp": now, "Price": price}])
                st.session_state["price_data"] = pd.concat(
                    [st.session_state["price_data"], new_row], ignore_index=True
                )
                
                # 최근 500개 틱 데이터만 유지
                if len(st.session_state["price_data"]) > 500:
                    st.session_state["price_data"] = st.session_state["price_data"].iloc[-500:]
        except Exception as e:
            pass

    def on_open(ws):
        # 구독 요청 메세지 전송
        subscribe_msg = {
            "type": "ticker",
            "symbols": [f"{symbol}_KRW"],
            "tickTypes": ["1M"]
        }
        ws.send(json.dumps(subscribe_msg))

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever()

# 웹소켓 백그라운드 스레드 시작
if not st.session_state["ws_connected"]:
    if st.sidebar.button("실시간 시세 연동 시작"):
        thread = threading.Thread(target=run_websocket, daemon=True)
        thread.start()
        st.session_state["ws_connected"] = True
        st.sidebar.success("실시간 연동이 시작되었습니다!")

# -----------------------------------------------------------------------------
# 5. 기술적 지표 계산 (이동평균선 & 스토캐스틱)
# -----------------------------------------------------------------------------
df = st.session_state["price_data"].copy()

if not df.empty and len(df) > 5:
    current_price = df["Price"].iloc[-1]
    prev_price = df["Price"].iloc[-2] if len(df) > 1 else current_price
    change = current_price - prev_price
    
    # 상단 대형 지표 전광판
    col1, col2, col3 = st.columns(3)
    col1.metric("현재가", f"{current_price:,.2f}", f"{change:,.2f}")
    col2.metric("최고가 (최근)", f"{df['Price'].max():,.2f}")
    col3.metric("최저가 (최근)", f"{df['Price'].min():,.2f}")

    # 이동평균선 계산
    df['MA5'] = df['Price'].rolling(window=5).mean()
    df['MA20'] = df['Price'].rolling(window=20).mean()
    df['MA60'] = df['Price'].rolling(window=60).mean()
    df['MA120'] = df['Price'].rolling(window=120).mean()

    # 스토캐스틱 슬로우(Stochastic Slow) 계산
    low_min = df['Price'].rolling(window=14).min()
    high_max = df['Price'].rolling(window=14).max()
    
    # 0으로 나누는 예외 방지
    denom = high_max - low_min
    denom = denom.replace(0, 1)
    
    df['%K'] = ((df['Price'] - low_min) / denom) * 100
    df['%D'] = df['%K'].rolling(window=3).mean()

    # -----------------------------------------------------------------------------
    # 6. Plotly 인터랙티브 차트 시각화
    # -----------------------------------------------------------------------------
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.08, 
        row_heights=[0.7, 0.3],
        subplot_titles=('실시간 가격 및 이동평균선(MA)', '스토캐스틱 슬로우(%K, %D)')
    )

    # [Subplot 1] 가격 라인 & 이동평균선
    fig.add_trace(go.Scatter(x=df.index, y=df['Price'], line=dict(color='white', width=1.5), name='체결가'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='magenta', width=1), name='5선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='20선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1), name='60선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA120'], line=dict(color='gray', width=1.5), name='120선(지지/저항)'), row=1, col=1)

    # [Subplot 2] 스토캐스틱
    fig.add_trace(go.Scatter(x=df.index, y=df['%K'], line=dict(color='orange', width=1), name='%K'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['%D'], line=dict(color='purple', width=1), name='%D'), row=2, col=1)

    # 스토캐스틱 과매수/과매도 기준선 표시
    fig.add_hline(y=80, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="blue", row=2, col=1)

    fig.update_layout(
        height=650, 
        template="plotly_dark", 
        showlegend=True,
        margin=dict(l=20, r=20, t=40, b=20)
    )
    
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("💡 사이드바의 '실시간 시세 연동 시작' 버튼을 누른 후 데이터를 수신할 때까지 잠시만 기다려주세요.")