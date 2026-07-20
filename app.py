import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
import websocket
import json
import threading
import requests

# -----------------------------------------------------------------------------
# 1. 페이지 및 자동 리프레시 설정 (1초마다 화면 갱신)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="산강식 실시간 선물/지수 분석 시스템",
    page_icon="📈",
    layout="wide"
)

# 1초(1000ms) 마다 스트리밋 화면 자동 재실행
st_autorefresh(interval=1000, key="realtime_tick")

st.title("⚡ 연결선물/지수 차트 및 산강식 지표 분석")

# -----------------------------------------------------------------------------
# 2. 세션 상태(Session State) 데이터 저장소 초기화
# -----------------------------------------------------------------------------
if "price_data" not in st.session_state:
    st.session_state["price_data"] = pd.DataFrame(columns=["Timestamp", "Price"])

if "ws_connected" not in st.session_state:
    st.session_state["ws_connected"] = False

# -----------------------------------------------------------------------------
# 3. 사이드바 설정 (한국투자증권 API 정보 및 종목 설정)
# -----------------------------------------------------------------------------
st.sidebar.header("🔑 캐스팅 및 차트 설정")
symbol = st.sidebar.text_input("종목 코드", "A01000", help="A01000: KOSPI200 연결선물")

st.sidebar.subheader("API 정보 (한국투자증권)")
app_key = st.sidebar.text_input("앱 키 (App Key)", type="password")
app_secret = st.sidebar.text_input("앱 시크릿 (App Secret)", type="password")
is_mock = st.sidebar.checkbox("모의투자 계좌 여부", value=True)

# -----------------------------------------------------------------------------
# 4. 한국투자증권 실시간 웹소켓(WebSocket) 수신 스레드
# -----------------------------------------------------------------------------
def get_approval_key(app_k, app_s, mock=True):
    """웹소켓 접속용 Approval Key 발급"""
    url = "https://openapivts.koreainvestment.com:29443" if mock else "https://openapi.koreainvestment.com:8001"
    headers = {"content-type": "application/json; charset=utf-8"}
    body = {"grant_type": "client_credentials", "appkey": app_k, "secretkey": app_s}
    try:
        res = requests.post(f"{url}/oauth2/Approval", headers=headers, data=json.dumps(body))
        return res.json().get("approval_key")
    except Exception as e:
        return None

def run_websocket(app_k, app_s, code, mock=True):
    approval_key = get_approval_key(app_k, app_s, mock)
    if not approval_key:
        st.session_state["ws_connected"] = False
        return

    # 모의투자 / 실전투자 웹소켓 URL 구분
    ws_url = "ws://ops.koreainvestment.com:21000" if mock else "ws://ops.koreainvestment.com:21000"
    
    def on_message(ws, message):
        try:
            # KIS 웹소켓 수신 데이터 파싱
            if message.startswith("0") or message.startswith("1"):
                tokens = message.split("|")
                tr_id = tokens[1]
                raw_data = tokens[3].split("^")
                
                # 선물 체결가 추출 (국내선물 체결 데이터 기준)
                price = float(raw_data[2]) # 현재가 / 체결가
                now = pd.Timestamp.now()
                
                new_row = pd.DataFrame([{"Timestamp": now, "Price": price}])
                st.session_state["price_data"] = pd.concat(
                    [st.session_state["price_data"], new_row], ignore_index=True
                )
                
                # 최근 500개 틱 데이터 유지를 통해 과부하 방지
                if len(st.session_state["price_data"]) > 500:
                    st.session_state["price_data"] = st.session_state["price_data"].iloc[-500:]
        except Exception:
            pass

    def on_open(ws):
        # 국내선물 실시간 체결가 구독 요청
        req_data = {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1", # 1: 등록
                "content-type": "utf-8"
            },
            "body": {
                "input": {
                    "tr_id": "H0IFCNT0", # 국내선물 실시간 체결가 TR
                    "tr_key": code
                }
            }
        }
        ws.send(json.dumps(req_data))

    ws = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message)
    ws.run_forever()

# 연동 시작 버튼
if not st.session_state["ws_connected"]:
    if st.sidebar.button("실시간 시세 연동 시작"):
        if app_key and app_secret:
            thread = threading.Thread(
                target=run_websocket, 
                args=(app_key, app_secret, symbol, is_mock), 
                daemon=True
            )
            thread.start()
            st.session_state["ws_connected"] = True
            st.sidebar.success(f"{symbol} 실시간 연동 시작!")
        else:
            st.sidebar.error("앱 키와 앱 시크릿을 입력해주세요.")

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
    col1.metric("현재가 (A01000)", f"{current_price:,.2f}", f"{change:,.2f}")
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
        subplot_titles=('연결선물 실시간 가격 및 이동평균선(MA)', '스토캐스틱 슬로우(%K, %D)')
    )

    # [Subplot 1] 체결가 & 이동평균선
    fig.add_trace(go.Scatter(x=df.index, y=df['Price'], line=dict(color='white', width=1.5), name='체결가'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='magenta', width=1), name='5선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name='20선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='green', width=1), name='60선'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA120'], line=dict(color='gray', width=1.5), name='120선(중요지지)'), row=1, col=1)

    # [Subplot 2] 스토캐스틱
    fig.add_trace(go.Scatter(x=df.index, y=df['%K'], line=dict(color='orange', width=1), name='%K'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['%D'], line=dict(color='purple', width=1), name='%D'), row=2, col=1)

    # 스토캐스틱 과매수/과매도 기준선
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
    st.info("💡 사이드바에 한국투자증권 앱 키와 앱 시크릿을 입력한 후 '실시간 시세 연동 시작' 버튼을 눌러주세요.")
