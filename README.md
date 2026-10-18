# Crypto Cue Desk (Tương thích với Cue by Manus)

Bản chuyển đổi (port) hoàn chỉnh từ dự án `hugoguerrap/crypto-claude-desk` sang kiến trúc **Cue by Manus** (Personal AI Agents với Cloud Computer, Group Chat, Email/SMS riêng và Persistent Background Automations).

## Cấu trúc thư mục
- `cue_desk_cli.py`: Công cụ dòng lệnh hợp nhất (tích hợp dữ liệu sàn CCXT, Orderbook Microstructure, Fear & Greed, DefiLlama TVL, các chỉ báo kỹ thuật RSI/MACD/Bollinger/ATR và trình giám sát SL/TP tự động).
- `db_manager.py`: Hệ thống cơ sở dữ liệu SQLite (`data/db/learning.db`) quản lý Paper Trading ($20,000 vốn khởi điểm), theo dõi dự đoán (Predictions) và thư viện mẫu hình tự học (Pattern Library: `SEEK` / `AVOID`).
- `cue_agents/`: Chứa System Prompts và thiết lập quyền hạn cho 3 Agent phối hợp trong Group Chat của Cue (`@Market-Scout`, `@Quant-Risk`, `@Desk-Lead`).
- `setup_cue_computer.sh`: Script cài đặt tự động bằng 1 lệnh trên Cloud Computer của Cue.

## Hướng dẫn sử dụng nhanh cho Cue by Manus
Chỉ cần gửi đường link GitHub của repository này cho Agent `@Desk-Lead` trong ứng dụng **Cue by Manus** với nội dung:
> "Hãy clone repo này về máy tính của bạn, chạy `bash setup_cue_computer.sh` để cài đặt và đọc các file trong thư mục `cue_agents/` để vận hành nhóm phân tích Crypto."
