import os
import time
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SmartWaterTank")

app = FastAPI(title="智慧水箱 AIoT 監控系統 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 系統當前狀態記憶體資料庫
STATE = {
    "telemetry": {
        "moisture": 52.0,            # 土壤濕度百分比 0 ~ 100%
        "water_level": 780,          # 水位感測 ADC 值 (0~4095)
        "is_water_low": False,       # 是否缺水 (防乾燒)
        "temperature": 27.5,         # 環境溫度 °C
        "humidity": 65.0,            # 空氣濕度 %
        "light_level": "normal",     # normal / strong / weak
        "pump_active": False,        # 馬達當前運作狀態
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    },
    "control": {
        "force_water": False,        # 手動強制澆水旗標 (由 ESP32 領取後執行 3 秒)
        "auto_mode": True,           # 是否啟用自動澆水
        "moisture_threshold": 35.0,  # 澆水門檻 (< 35% 啟動澆水)
        "temp_guard_threshold": 32.0,# 高溫避險門檻 (> 32°C 禁澆)
        "water_low_threshold": 400   # 水箱缺水警戒 ADC 門檻
    },
    "alerts": {
        "last_water_low_push": 0,    # 上次發送缺水警報的 timestamp (避免洗版，間隔 2 小時)
        "last_watering_push": 0
    },
    "config": {
        "line_channel_access_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
        "line_user_id": os.getenv("LINE_USER_ID", ""),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "")
    },
    "history": []                    # 最近 60 筆時序紀錄供前端繪製圖表
}

# 初始化幾筆假資料以防一啟動前端圖表為空
now_ts = time.time()
for i in range(12, 0, -1):
    STATE["history"].append({
        "time": datetime.fromtimestamp(now_ts - i * 300).strftime("%H:%M"),
        "moisture": round(50 + (i % 5) * 1.5, 1),
        "temperature": round(26.5 + (i % 3) * 0.8, 1),
        "humidity": round(64 + (i % 4) * 1.2, 1)
    })

# Pydantic 數據模型
class TelemetryInput(BaseModel):
    moisture: float
    water_level: Optional[int] = 800
    is_water_low: Optional[bool] = False
    temperature: float
    humidity: float
    light_level: Optional[str] = "normal"
    pump_active: Optional[bool] = False

class WaterCommand(BaseModel):
    duration_sec: Optional[int] = 3

class ConfigUpdate(BaseModel):
    line_channel_access_token: Optional[str] = None
    line_user_id: Optional[str] = None
    gemini_api_key: Optional[str] = None

class AskAIInput(BaseModel):
    plant_name: str
    user_question: Optional[str] = ""

# 計算 OLED 機器人表情狀態
def compute_robot_state(telemetry: dict) -> dict:
    """
    根據計畫書五大狀態機：
    A: 正常愉悅 ( ^▽^ ) - 土壤 40~80%、水箱正常
    B: 口渴哭泣 ( >_< ) - 土壤 < 35%，等待補水
    C: 高溫流汗 ( ;' 0 ') - 溫度 > 32°C，烈日避險中
    D: 缺水暈眩 ( X _ X ) - 水箱見底，發出警告
    """
    if telemetry["is_water_low"]:
        return {
            "code": "D",
            "name": "缺水暈眩",
            "face": "( X _ X )",
            "desc": "水箱見底！馬達已強制鎖死保護，請儘速加水！",
            "color": "#ef4444"
        }
    elif telemetry["temperature"] > STATE["control"]["temp_guard_threshold"]:
        return {
            "code": "C",
            "name": "高溫流汗",
            "face": "( ;' 0 ')",
            "desc": "環境高溫避險中 (>32°C)，暫緩澆水防止悶爛根系。",
            "color": "#f59e0b"
        }
    elif telemetry["moisture"] < STATE["control"]["moisture_threshold"]:
        return {
            "code": "B",
            "name": "口渴哭泣",
            "face": "( > _ < )",
            "desc": "土壤過乾 (<35%)，需要及時補水滴灌！",
            "color": "#3b82f6"
        }
    else:
        return {
            "code": "A",
            "name": "正常愉悅",
            "face": "( ^ ▽ ^ )",
            "desc": "水箱正常、溫濕度適宜，植物茁壯成長中！",
            "color": "#10b981"
        }

# LINE Messaging API 發送工具
def send_line_push_message(text: str, user_id: Optional[str] = None) -> bool:
    token = STATE["config"]["line_channel_access_token"]
    target_user = user_id or STATE["config"]["line_user_id"]
    if not token or not target_user:
        logger.warning("未設定 LINE Channel Access Token 或 User ID，略過推播。")
        return False
    
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "to": target_user,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        if res.status_code == 200:
            logger.info("LINE Push 訊息發送成功！")
            return True
        else:
            logger.error(f"LINE Push 失敗: {res.status_code} {res.text}")
            return False
    except Exception as e:
        logger.error(f"發送 LINE Push 異常: {e}")
        return False

def reply_line_message(reply_token: str, text: str) -> bool:
    token = STATE["config"]["line_channel_access_token"]
    if not token:
        return False
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=8)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"LINE Reply 異常: {e}")
        return False

# ==================== REST API 端點 ====================

@app.get("/api/status")
def get_status():
    """取得系統完整即時狀態（提供前端 Web 儀表板與輪詢使用）"""
    t = STATE["telemetry"]
    robot = compute_robot_state(t)
    return {
        "telemetry": t,
        "control": STATE["control"],
        "robot": robot,
        "config_status": {
            "has_line_token": bool(STATE["config"]["line_channel_access_token"]),
            "has_line_user": bool(STATE["config"]["line_user_id"]),
            "has_gemini_key": bool(STATE["config"]["gemini_api_key"])
        }
    }

@app.post("/api/telemetry")
def receive_telemetry(data: TelemetryInput, background_tasks: BackgroundTasks):
    """
    ESP32 定期上報感測數據（輕量 HTTP POST，耗時 < 50ms）
    回傳指令：例如 force_water=true 時 ESP32 啟動澆水 3 秒
    """
    now = datetime.now()
    t = STATE["telemetry"]
    t["moisture"] = round(data.moisture, 1)
    t["water_level"] = data.water_level
    t["is_water_low"] = data.is_water_low or (data.water_level < STATE["control"]["water_low_threshold"])
    t["temperature"] = round(data.temperature, 1)
    t["humidity"] = round(data.humidity, 1)
    t["light_level"] = data.light_level or "normal"
    t["pump_active"] = data.pump_active or False
    t["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    # 記錄歷史資料 (限制最多 60 筆)
    STATE["history"].append({
        "time": now.strftime("%H:%M:%S"),
        "moisture": t["moisture"],
        "temperature": t["temperature"],
        "humidity": t["humidity"]
    })
    if len(STATE["history"]) > 60:
        STATE["history"].pop(0)

    # 檢查是否觸發 LINE 缺水警報 (每 2 小時最多推播一次，避免洗版)
    current_ts = time.time()
    if t["is_water_low"]:
        if current_ts - STATE["alerts"]["last_water_low_push"] > 7200: # 2 小時
            STATE["alerts"]["last_water_low_push"] = current_ts
            alert_text = (
                "⚠️【緊急警告：智慧水箱缺水】\n"
                "儲水箱水量已低於安全防線！\n"
                "已強制鎖死馬達防乾燒，請儘速補充水源！\n"
                f"當前土壤濕度：{t['moisture']}%"
            )
            background_tasks.add_task(send_line_push_message, alert_text)

    # 取出並重設手動澆水指令 (ESP32 領取後會啟動澆水)
    trigger_water = STATE["control"]["force_water"]
    if trigger_water:
        STATE["control"]["force_water"] = False # 領取後復原

    return {
        "status": "ok",
        "force_water": trigger_water,
        "auto_mode": STATE["control"]["auto_mode"]
    }

@app.post("/api/water")
def trigger_manual_water(cmd: WaterCommand = WaterCommand(), background_tasks: BackgroundTasks = None):
    """使用者在 Web 儀表板或 LINE 點擊『手動強制澆水』"""
    if STATE["telemetry"]["is_water_low"]:
        raise HTTPException(status_code=400, detail="水箱缺水，馬達處於安全鎖死狀態，無法澆水！")
    
    STATE["control"]["force_water"] = True
    STATE["telemetry"]["pump_active"] = True

    # 發送 LINE 補水通知
    notify_text = (
        "🌱【自動滴灌通知】\n"
        f"已成功觸發 {cmd.duration_sec} 秒定量滴灌！\n"
        f"補水前土壤濕度：{STATE['telemetry']['moisture']}%\n"
        f"環境氣溫：{STATE['telemetry']['temperature']}°C"
    )
    if background_tasks:
        background_tasks.add_task(send_line_push_message, notify_text)
    else:
        send_line_push_message(notify_text)

    return {"status": "success", "message": f"已發送澆水指令 ({cmd.duration_sec} 秒)"}

@app.get("/api/history")
def get_history():
    """回傳感測歷史時序數據（供前端圖表繪製折線圖）"""
    return {"history": STATE["history"]}

@app.post("/api/simulate")
def simulate_data(data: TelemetryInput):
    """
    評審演示或開發測試用：手動拉動數值模擬 ESP32 回傳
    """
    t = STATE["telemetry"]
    t["moisture"] = round(data.moisture, 1)
    t["water_level"] = data.water_level
    t["is_water_low"] = data.is_water_low or (data.water_level < STATE["control"]["water_low_threshold"])
    t["temperature"] = round(data.temperature, 1)
    t["humidity"] = round(data.humidity, 1)
    t["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 紀錄歷史
    STATE["history"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "moisture": t["moisture"],
        "temperature": t["temperature"],
        "humidity": t["humidity"]
    })
    if len(STATE["history"]) > 60:
        STATE["history"].pop(0)

    robot = compute_robot_state(t)
    return {"status": "simulated", "telemetry": t, "robot": robot}

@app.post("/api/config")
def update_config(cfg: ConfigUpdate):
    """更新 LINE 或 Gemini 金鑰設定"""
    if cfg.line_channel_access_token is not None:
        STATE["config"]["line_channel_access_token"] = cfg.line_channel_access_token.strip()
    if cfg.line_user_id is not None:
        STATE["config"]["line_user_id"] = cfg.line_user_id.strip()
    if cfg.gemini_api_key is not None:
        STATE["config"]["gemini_api_key"] = cfg.gemini_api_key.strip()
    return {"status": "success", "config": {
        "line_token_set": bool(STATE["config"]["line_channel_access_token"]),
        "line_user_set": bool(STATE["config"]["line_user_id"]),
        "gemini_key_set": bool(STATE["config"]["gemini_api_key"])
    }}

@app.post("/api/line/test-alert")
def test_line_alert():
    """測試發送 LINE 警報推播訊息"""
    text = (
        "🤖【智慧水箱連線測試】\n"
        "LINE Messaging API 連線成功！\n"
        f"當前土壤濕度：{STATE['telemetry']['moisture']}%\n"
        f"水箱狀態：{'⚠️ 缺水' if STATE['telemetry']['is_water_low'] else '✅ 正常'}\n"
        f"氣溫：{STATE['telemetry']['temperature']}°C / 濕度：{STATE['telemetry']['humidity']}%\n"
        "系統已準備好為您的植物保駕護航！🌿"
    )
    ok = send_line_push_message(text)
    if not ok:
        raise HTTPException(status_code=400, detail="LINE 推播失敗，請檢查 Token 與 User ID 是否正確設定！")
    return {"status": "sent"}

# ==================== AI 園藝顧問模組 ====================

def query_gemini_or_expert(plant_name: str, question: str, telemetry: dict) -> str:
    """
    結合當前實時感測數據注入提示詞，調用 Gemini API 或內建高精度園藝專家規則庫
    """
    api_key = STATE["config"]["gemini_api_key"]
    moisture = telemetry["moisture"]
    temp = telemetry["temperature"]
    humidity = telemetry["humidity"]
    water_status = "缺水告急" if telemetry["is_water_low"] else "正常"

    system_prompt = (
        f"你是一位專業且溫暖的植物學專家與 AIoT 智慧園藝顧問。\n"
        f"當前花盆周圍的真實環境即時監測數據如下：\n"
        f"- 土壤含水率：{moisture}%\n"
        f"- 環境氣溫：{temp}°C\n"
        f"- 空氣相對濕度：{humidity}%\n"
        f"- 水箱狀態：{water_status}\n\n"
        f"請針對使用者詢問的植物「{plant_name}」，結合上述目前的即時環境數據進行專業分析，"
        f"給予精簡、清晰、條理分明的照護建議（包含：需不需要立即澆水、目前的溫度對它是否適宜、日照與通風注意事項）。"
    )

    if api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{system_prompt}\n\n使用者具體問題：{question or '請評估目前狀態適不適合生長並給予照料建議'}"}
                        ]
                    }
                ]
            }
            res = requests.post(url, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                logger.error(f"Gemini API 回傳錯誤: {res.text}")
        except Exception as e:
            logger.error(f"Gemini API 連線異常: {e}")

    # 內建專家規則庫（即使在沒有外部網路或未填 API Key 時仍能提供極度精準專業的即時照護分析）
    plant = plant_name.strip()
    advice = []
    advice.append(f"🌿【{plant} 專屬 AI 園藝照護診斷】")
    advice.append(f"📊 當前環境數值：土壤濕度 {moisture}% ｜ 氣溫 {temp}°C ｜ 空氣濕度 {humidity}%\n")

    # 澆水與濕度建議
    if "多肉" in plant or "仙人掌" in plant:
        if moisture > 40:
            advice.append("💧 澆水建議：【切勿澆水！】多肉植物耐旱怕澇，當前濕度仍高，請保持盆土通風乾燥，避免爛根。")
        else:
            advice.append("💧 澆水建議：土壤已乾透，可在涼爽傍晚進行微量補水，乾透澆透。")
    elif "薄荷" in plant or "迷迭香" in plant or "九層塔" in plant:
        if moisture < 35:
            if temp > 32:
                advice.append("💧 澆水建議：土壤雖然偏乾（<35%），但目前氣溫高達 32°C 以上，建議移至陰涼通風處，待傍晚降溫後再啟動滴灌，避免根部悶爛！")
            else:
                advice.append("💧 澆水建議：香草類植物生長旺盛需水較多，目前土壤濕度偏低，建議立即啟動 3 秒滴灌補水。")
        else:
            advice.append("💧 澆水建議：當前水分充足適中，保持通風即可。")
    else:
        if moisture < 35:
            advice.append("💧 澆水建議：土壤濕度低於 35%，建議進行定量滴灌補充水分。")
        elif moisture > 80:
            advice.append("💧 澆水建議：水分非常充沛，暫時無需澆水，請注意花盆排水通暢。")
        else:
            advice.append("💧 澆水建議：土壤濕度維持在理想的 40%~80% 區間，狀況良好。")

    # 溫度與通風建議
    if temp > 32:
        advice.append(f"🌡️ 溫度警示：當前溫度 {temp}°C 偏高，系統已啟動高溫避險。請確保擺放於遮蔭通風良好的陽台位置。")
    elif temp < 15:
        advice.append(f"🌡️ 溫度提醒：當前溫度 {temp}°C 較低，植物代謝減緩，應減少澆水量防止凍傷。")
    else:
        advice.append(f"🌡️ 溫度評估：{temp}°C 是絕大多數綠色觀葉植物的舒適生長區間。")

    advice.append("\n💡 提示：本建議已自動融入您水箱的即時傳感器數據！")
    return "\n".join(advice)

@app.post("/api/ai/ask")
def ask_ai(req: AskAIInput):
    """前端 Web 儀表板提問 AI 園藝顧問"""
    answer = query_gemini_or_expert(req.plant_name, req.user_question, STATE["telemetry"])
    return {
        "status": "ok",
        "plant": req.plant_name,
        "answer": answer,
        "telemetry_used": {
            "moisture": STATE["telemetry"]["moisture"],
            "temp": STATE["telemetry"]["temperature"],
            "humidity": STATE["telemetry"]["humidity"]
        }
    }

# ==================== LINE Webhook 整合 ====================

@app.post("/api/line/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    LINE Messaging API Webhook 端點
    支援在 LINE 聊天室中：
    - 輸入「狀態」或「水箱」：即刻回傳即時環境數據與表情
    - 輸入「澆水」：直接由 LINE 觸發手動滴灌 3 秒
    - 輸入「薄荷」、「多肉」或任何植物問題：自動調用 AI 顧問並在 LINE 回覆
    """
    body = await request.body()
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse({"status": "invalid json"}, status_code=400)

    events = data.get("events", [])
    for event in events:
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            reply_token = event.get("replyToken")
            user_msg = event["message"]["text"].strip()
            user_id = event.get("source", {}).get("userId")

            # 若尚未綁定 User ID，自動記憶發話者的 User ID
            if user_id and not STATE["config"]["line_user_id"]:
                STATE["config"]["line_user_id"] = user_id
                logger.info(f"自動綁定 LINE User ID: {user_id}")

            t = STATE["telemetry"]
            robot = compute_robot_state(t)

            if user_msg in ["狀態", "查詢", "水箱", "即時狀態"]:
                reply_text = (
                    f"🤖【智慧水箱目前狀態】\n"
                    f"表情狀態：{robot['face']} {robot['name']}\n"
                    f"🌱 土壤濕度：{t['moisture']}%\n"
                    f"💧 水箱狀態：{'⚠️ 見底鎖死！' if t['is_water_low'] else '✅ 正常存水'}\n"
                    f"🌡️ 環境氣溫：{t['temperature']}°C\n"
                    f"🌫️ 空氣濕度：{t['humidity']}%\n"
                    f"⚡ 馬達狀態：{'運轉滴灌中' if t['pump_active'] else '待機中'}\n"
                    f"🕒 更新時間：{t['updated_at']}"
                )
            elif user_msg in ["澆水", "手動澆水", "補水"]:
                if t["is_water_low"]:
                    reply_text = "❌ 水箱缺水警戒中，為保護馬達防乾燒，目前禁止澆水！請先為水箱加水。"
                else:
                    STATE["control"]["force_water"] = True
                    reply_text = "💧 已收到澆水指令！馬達將啟動 3 秒微調滴灌。"
            elif user_msg in ["說明", "功能", "help", "幫助"]:
                reply_text = (
                    "📖【智慧水箱 LINE 控制指令】\n"
                    "1. 傳送「狀態」：查看當前感測數據與機器人表情\n"
                    "2. 傳送「澆水」：觸發 3 秒定量手動滴灌\n"
                    "3. 傳送植物名稱（如「薄荷照顧」、「多肉怎麼顧」）：取得帶入當前即時環境的 AI 照護建議！"
                )
            else:
                # 調用 AI 園藝顧問
                reply_text = query_gemini_or_expert(user_msg, user_msg, t)

            background_tasks.add_task(reply_line_message, reply_token, reply_text)

    return JSONResponse({"status": "ok"})

# 掛載 Web 靜態資源目錄
WEB_DIR = "/Users/ray/Desktop/智慧水箱/web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
