# 太陽能 AIoT 自動滴灌與遠端監控儀表板 (Solar AIoT Smart Irrigation Dashboard)

[![Cloudflare Pages](https://img.shields.io/badge/Cloudflare-Pages%20Ready-F38020?logo=cloudflare&logoColor=white)](https://pages.cloudflare.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Chart.js](https://img.shields.io/badge/Chart.js-FF6384?logo=chartdotjs&logoColor=white)](https://www.chartjs.org/)
[![ESP32 AIoT](https://img.shields.io/badge/Hardware-ESP32%20NodeMCU-E7352C?logo=espressif&logoColor=white)](https://www.espressif.com/)

專為高質感、現代化與穩定運行所設計的「**太陽能 AIoT 自動滴灌與遠端監控系統**」純前端靜態儀表板。具備雙重避險防護機制、ESP32 邊緣感知、Cloudflare 邊緣 API 整合、Chart.js 時序趨勢圖表與 AI 智慧園藝顧問。

---

## 🌟 核心特色與功能架構

1. **現代化 Nature-Tech 深色玻璃態設計 (Glassmorphism & RWD)**
   - 採用深藍冷岩底色搭配生態翡翠綠、光伏琥珀金與水流青藍霓虹光芒。
   - 支援手機（Mobile）、平板（Tablet）與桌機（Desktop）全解析度響應式排版（RWD）。

2. **微型氣象站四大即時感測指標**
   - **🌱 土壤含水率 (電容式 ADC 感測)**：動態含水量條狀圖、乾燥警戒指標與生長舒適區間標記。
   - **🌡️ 環境氣溫 (數位溫濕度感測)**：即時氣溫監測與高溫避險門檻判定。
   - **🌫️ 空氣相對濕度**：環境蒸散速率與通風評估。
   - **☀️ 日照光照強度**：即時環境光量評估與太陽能充電效能提示。

3. **雙重避險保護與遠端手動澆水控制**
   - **防乾燒保險**：水箱水位見底（`water_ok === false`）時，系統立即於前端顯示紅色警報橫幅，並將手動澆水按鈕強制鎖死反灰，阻斷水泵空轉燒毀。
   - **高溫避險暫緩**：當氣溫超過 32°C 時，自動判定為烈日避險，延後澆水以避免高溫悶根。
   - **非同步狀態握手**：點擊「🌱 手動一鍵強制澆水 (3秒微調滴灌)」按鈕時，發送 `POST /api/pump` 並即時呈現旋轉載入動畫，直到 ESP32 執行完畢並在下次輪詢回傳 `force_pump: false` 時恢復正常。

4. **ESP32 實體 OLED 動態表情看板模擬**
   - 擬真還原 ESP32 搭載之 SSD1306 0.96 吋 I2C 螢幕動態狀態：
     - `( ^ ▽ ^ )` **植物成長愉悅中**：水箱存水充足、溫濕度適宜。
     - `( > _ < )` **口渴哭泣**：土壤含水率低於 35%，等待補水。
     - `( ;' 0 ')` **高溫流汗**：環境氣溫高於 32°C，烈日避險防止悶爛根系。
     - `( X _ X )` **缺水暈眩**：儲水箱缺水見底，防乾燒保護啟動。

5. **歷史趨勢平滑折線圖 (Chart.js)**
   - 自動向 `/api/history` 每 30 秒輪詢時序數據。
   - 支援綜合雙軸對比、土壤濕度、氣溫與空氣濕度分頁切換。
   - 內建優雅漸層填色與暗黑主題格線。

6. **AI 園藝植物健檢顧問**
   - **動態組裝即時提示詞**：自動將水箱目前的即時數據（土壤濕度、氣溫、濕度、光照、水箱蓄水）組裝成完整的農藝提問詞。
   - **支援自訂金鑰**：彈窗支援直接填入個人的 Google Gemini API Key 或 OpenAI API Key。
   - **內建農藝規則引擎**：若未填入金鑰，自動啟用內建植物生理專家模型，即刻產出專業診斷與養護指引。
   - **一鍵複製與語音朗讀**：支援將帶有即時數據的提示詞一鍵複製至 ChatGPT/Claude，並支援 Web Speech API 語音朗讀。

---

## 📡 後端 API 規格 (Cloudflare Workers)

API Base URL：`https://plant-iot-api.bqcgnbp9m4.workers.dev`

| 端點 | 方法 | 呼叫週期 | 說明 |
| :--- | :---: | :---: | :--- |
| `/api/status` | `GET` | 每 3 秒 | 輪詢最新狀態（土壤濕度、氣溫、空氣濕度、日照、水箱狀態、水泵旗標） |
| `/api/history` | `GET` | 每 30 秒 | 抓取時序陣列供 Chart.js 繪製趨勢曲線 |
| `/api/pump` | `POST` | 手動觸發 | 排程強制手動滴灌 3 秒指令 |

---

## 🚀 部署至 Cloudflare Pages 靜態網站

本專案採用**零打包依賴的純靜態架構**（Tailwind CDN + Chart.js + FontAwesome 6），非常適合直接託管在 Cloudflare Pages：

1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/) 並點選 **Workers & Pages** > **Create application** > **Pages**。
2. 連結 GitHub 儲存庫：`Ray-0420/plant-iot-dashboard`。
3. 部署設定：
   - **Framework preset**：`None`
   - **Build command**：（留空）
   - **Build output directory**：（留空，或填寫 `/`）
4. 點選 **Save and Deploy**，即可在數秒內全球邊緣加速上線！

---

## 🛠️ 本地測試與預覽

直接在瀏覽器開啟 `index.html`，或使用 Python 快速架設本地測試伺服器：

```bash
# 在專案目錄下啟動靜態伺服器
python3 -m http.server 8080

# 於瀏覽器開啟 http://localhost:8080 即可瀏覽
```

---

## 📜 專案技術棧

- **Frontend Core**：HTML5 / Modern JavaScript (ES6+)
- **Styling**：Tailwind CSS (JIT CDN), FontAwesome 6, Google Fonts (Outfit / Noto Sans TC / JetBrains Mono)
- **Data Visualization**：Chart.js 4.4.1
- **IoT & Edge**：ESP32 NodeMCU, Cloudflare Workers, Cloudflare D1
- **AI Integrations**：Google Gemini 1.5 Flash API, OpenAI API, Local Agronomy Rules Engine
