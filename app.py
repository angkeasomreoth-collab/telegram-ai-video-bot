import os
import re
import time
import asyncio
import threading
import cv2
from PIL import Image
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from flask import Flask

# ================= FLASK SERVER FOR RENDER (FREE WEB SERVICE) =================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "AI Video Prompt Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ================= 1. CONFIGURATION =================
TELEGRAM_BOT_TOKEN = "8994686368:AAEa2EYdCFqrlpRWHYG7T-z1Nbmlk1IIolY"
GEMINI_API_KEY = "AQ.Ab8RN6Lf2Szg-t97nEE6grrhQYuqjOP3rYHVJ5L1jJmN9yPKbw"

client = genai.Client(api_key=GEMINI_API_KEY)
USER_SESSIONS = {}

# ================= 2. HELPER FUNCTIONS =================
def parse_srt_with_pauses(srt_filepath, min_pause_threshold=1.5):
    with open(srt_filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    pattern = re.compile(
        r'(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n(.*?)(?=\n\n|\n\d+\s*\n|\Z)',
        re.DOTALL
    )
    matches = pattern.findall(content)

    def time_to_sec(t_str):
        t_str = t_str.replace(',', '.')
        parts = t_str.split(':')
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

    timeline = []
    last_end_sec = 0.0

    for m in matches:
        start_sec = time_to_sec(m[1])
        end_sec = time_to_sec(m[2])
        text = m[3].replace('\n', ' ').strip()

        if start_sec - last_end_sec >= min_pause_threshold:
            timeline.append({
                "type": "PAUSE",
                "mid": (last_end_sec + start_sec) / 2.0,
                "duration": start_sec - last_end_sec,
                "time_range": f"{int(last_end_sec)}s - {int(start_sec)}s",
                "text": "[SILENT PAUSE / DRAMATIC INTERLUDE]"
            })

        timeline.append({
            "type": "DIALOGUE",
            "mid": (start_sec + end_sec) / 2.0,
            "duration": end_sec - start_sec,
            "time_range": f"{m[1][:8]} - {m[2][:8]}",
            "text": text
        })
        last_end_sec = end_sec

    return timeline

# ================= 3. BOT HANDLERS =================
def init_session(chat_id):
    if chat_id not in USER_SESSIONS:
        USER_SESSIONS[chat_id] = {
            "style": "Photorealistic 8k, live-action cinematic movie shot",
            "costume": "Authentic ancient Chinese Hanfu robes",
            "video_path": None,
            "srt_path": None
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    init_session(chat_id)
    await update.message.reply_text(
        "👋 **សូមស្វាគមន៍មកកាន់ AI Video Prompt Studio Bot!**\n\n"
        "👉 សូមផ្ញើ **File Subtitle (.srt)** ចូលមុន ឬផ្ញើ **វីដេអូ (.mp4)** ចូលផ្ទាល់តែម្តង។",
        parse_mode="Markdown"
    )

async def show_style_options(message):
    keyboard = [
        [InlineKeyboardButton("🎬 Hyper-Realistic 8K", callback_data="style_hyper"),
         InlineKeyboardButton("🧸 3D Pixar Style", callback_data="style_3d")],
        [InlineKeyboardButton("🌸 Modern Anime 2D", callback_data="style_anime"),
         InlineKeyboardButton("🎞 Keep Original", callback_data="style_orig")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        "🎨 **ជំហានទី ១៖ ជ្រើសរើសស្ទីលរូបភាព (Visual Style)**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    init_session(chat_id)
    os.makedirs(f"temp_{chat_id}", exist_ok=True)

    msg = update.message
    status_msg = await msg.reply_text("⏳ កំពុងទាញយក File...")

    if msg.document:
        doc = msg.document
        file_name = doc.file_name.lower()
        file = await context.bot.get_file(doc.file_id)

        if file_name.endswith('.srt'):
            srt_path = f"temp_{chat_id}/sub.srt"
            await file.download_to_drive(srt_path)
            USER_SESSIONS[chat_id]["srt_path"] = srt_path
            await status_msg.edit_text("✅ បានទទួលឯកសារ SRT! ឥឡូវសូមផ្ញើ File វីដេអូបន្ត។")
            return

        elif file_name.endswith(('.mp4', '.mov', '.avi', '.mkv')):
            vid_path = f"temp_{chat_id}/video.mp4"
            await file.download_to_drive(vid_path)
            USER_SESSIONS[chat_id]["video_path"] = vid_path

    elif msg.video:
        file = await context.bot.get_file(msg.video.file_id)
        vid_path = f"temp_{chat_id}/video.mp4"
        await file.download_to_drive(vid_path)
        USER_SESSIONS[chat_id]["video_path"] = vid_path

    await status_msg.delete()
    await show_style_options(msg)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    init_session(chat_id)

    if data.startswith("style_"):
        if data == "style_hyper":
            USER_SESSIONS[chat_id]["style"] = "Photorealistic 8k, live-action cinematic movie shot, natural skin pores, realistic lighting"
        elif data == "style_3d":
            USER_SESSIONS[chat_id]["style"] = "High-end 3D Pixar Disney animation style, smooth stylized character design, vibrant lighting"
        elif data == "style_anime":
            USER_SESSIONS[chat_id]["style"] = "Modern cinematic 2D anime style, Makoto Shinkai aesthetic, clean lines"
        else:
            USER_SESSIONS[chat_id]["style"] = "Maintain exact original video rendering style"

        keyboard = [
            [InlineKeyboardButton("👘 ចិនបុរាណ (Hanfu)", callback_data="costume_hanfu"),
             InlineKeyboardButton("🥻 ខ្មែរបុរាណ (Angkorian)", callback_data="costume_khmer_anc")],
            [InlineKeyboardButton("👔 ខ្មែរសម័យ (Khmer Silk)", callback_data="costume_khmer_mod"),
             InlineKeyboardButton("🧥 ស៊ីវិល័យសម័យថ្មី (Modern)", callback_data="costume_modern")],
            [InlineKeyboardButton("🔄 តាមសំលៀកបំពាក់ដើម", callback_data="costume_orig")]
        ]
        await query.edit_message_text(
            "👗 **ជំហានទី ២៖ ជ្រើសរើសសំលៀកបំពាក់សម័យកាល (Wardrobe)**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("costume_"):
        if data == "costume_hanfu":
            USER_SESSIONS[chat_id]["costume"] = "Authentic ancient Chinese Hanfu robes, silk embroidery, traditional hairpins"
        elif data == "costume_khmer_anc":
            USER_SESSIONS[chat_id]["costume"] = "Ancient Khmer Empire (Angkorian) attire: traditional Sampot Chang Kben, golden ornate jewelry"
        elif data == "costume_khmer_mod":
            USER_SESSIONS[chat_id]["costume"] = "Modern elegant-cut Khmer silk (Hol/Phamung) fashion"
        elif data == "costume_modern":
            USER_SESSIONS[chat_id]["costume"] = "Modern luxury tailored streetwear and designer fashion"
        else:
            USER_SESSIONS[chat_id]["costume"] = "Keep original clothing from the footage"

        await query.edit_message_text("⏳ **កំពុងវិភាគវីដេអូ និងបង្កើត Prompts តាម Gemini AI... សូមរង់ចាំបន្តិច!**", parse_mode="Markdown")
        asyncio.create_task(process_video_task(chat_id, context))

async def process_video_task(chat_id, context):
    session = USER_SESSIONS[chat_id]
    vid_path = session.get("video_path")
    srt_path = session.get("srt_path")
    out_dir = f"temp_{chat_id}/sync_frames"
    os.makedirs(out_dir, exist_ok=True)

    if not vid_path or not os.path.exists(vid_path):
        await context.bot.send_message(chat_id=chat_id, text="❌ មិនមាន File វីដេអូទេ! សូមផ្ញើវីដេអូឡើងវិញ។")
        return

    cap = cv2.VideoCapture(vid_path)
    frame_tasks = []

    if srt_path and os.path.exists(srt_path):
        timeline = parse_srt_with_pauses(srt_path)
        for idx, item in enumerate(timeline, 1):
            cap.set(cv2.CAP_PROP_POS_MSEC, item['mid'] * 1000)
            ret, frame = cap.read()
            if ret:
                fpath = os.path.join(out_dir, f"scene_{idx:03d}.jpg")
                cv2.imwrite(fpath, frame)
                frame_tasks.append({
                    "type": item['type'],
                    "time_range": item['time_range'],
                    "line_text": item['text'],
                    "duration": item['duration'],
                    "img_path": fpath
                })
    else:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration_sec = total_frames / fps
        sec = 0.0
        idx = 1
        while sec < duration_sec:
            cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ret, frame = cap.read()
            if not ret:
                break
            fpath = os.path.join(out_dir, f"scene_{idx:03d}.jpg")
            cv2.imwrite(fpath, frame)
            frame_tasks.append({
                "type": "STANDARD",
                "time_range": f"{int(sec)}s",
                "line_text": "",
                "duration": 3.0,
                "img_path": fpath
            })
            sec += 3.0
            idx += 1
    cap.release()

    output_txt = f"temp_{chat_id}/AI_Video_Prompts.txt"
    with open(output_txt, "w", encoding="utf-8") as f:
        for idx, task in enumerate(frame_tasks, 1):
            for attempt in range(1, 6):
                try:
                    pil_img = Image.open(task['img_path'])
                    prompt_instruction = f"""
You are an elite Hollywood Director, Cinematographer, and Sound Designer.
Generate a structured production prompt for Scene #{idx} at [{task['time_range']}].

VISUAL STYLE: {session['style']}
COSTUME DIRECTIVE: {session['costume']}
CURRENT DIALOGUE: "{task['line_text']}"

DIRECTING DIRECTIVES:
1. CAMERA SETUP: Identify exact camera shot type, angle, lens depth, and camera motion.
2. DIALOGUE / VOICEOVER: Provide exact translated dialogue in natural, dramatic, spoken Khmer (ភាសាខ្មែរ).
3. SOUND DESIGN: Identify realistic SFX / Foley sound effects (footsteps, clothing rustle, ambient background).
4. ACTING & LIP-SYNC: Active lip-sync articulating words if speaking; closed mouth if silent pause.

OUTPUT FORMAT:
[VOICEOVER / DIALOGUE ({task['time_range']})]:
Line: "<Translated Spoken Line in Khmer>"
Camera Setup: <Shot Type, Lens, Motion>
SFX / Foley: <Sound Effects>

[AI VIDEO GENERATOR PROMPT]:
<Single cohesive paragraph for Kling/Runway Gen-3 starting immediately with camera setup, style, costume, acting, and background.>
"""
                    res = client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=[prompt_instruction, pil_img]
                    )
                    f.write(f"==================================================\n")
                    f.write(f"🎬 SCENE #{idx:02d} | [{task['type']}] | [{task['time_range']}]\n")
                    f.write(f"==================================================\n")
                    f.write(f"{res.text.strip()}\n\n\n")
                    f.flush()
                    break
                except Exception as e:
                    if "503" in str(e) or "429" in str(e):
                        time.sleep(attempt * 4)
                    else:
                        time.sleep(2)

    await context.bot.send_document(
        chat_id=chat_id,
        document=open(output_txt, "rb"),
        caption=f"🎉 **រួចរាល់! ឯកសារ Prompts ត្រូវបានបង្កើតជោគជ័យ (សរុប {len(frame_tasks)} Scenes)។**",
        parse_mode="Markdown"
    )

# ================= 4. MAIN ENTRY =================
if __name__ == "__main__":
    # ចាប់ផ្តើម Web Server សម្រាប់ Render
    threading.Thread(target=run_flask, daemon=True).start()

    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(request_config).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, handle_media))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("🤖 Telegram Bot is running smoothly...")
    app.run_polling(drop_pending_updates=True)
