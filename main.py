import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes, JobQueue
import logging
import json
import os
import base64
import time

# --- কনফিগারেশন: Railway Environment Variables থেকে লোড হবে ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")  
try:
    ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID")) 
    CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
except (TypeError, ValueError):
    # যদি Railway-তে ভ্যারিয়েবল সেট না থাকে বা ভুল ফরম্যাটে থাকে
    ADMIN_USER_ID = 0
    CHANNEL_ID = 0

BOT_USERNAME = os.environ.get("BOT_USERNAME")  
DATA_FILE = os.environ.get("DATA_FILE", "video_data.json")
DELETION_TIME_SECONDS = 4 * 3600  # ৪ ঘন্টা পর ইউজারের ভিডিও অটো ডিলিট

STAGED_UPLOADS = {}

# --- লগিং ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ডাটা লোড/সেভ ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.error("JSON ফাইল লোড করতে সমস্যা হয়েছে, নতুন ডাটা স্ট্রাকচার তৈরি হচ্ছে।")
            return {"videos": {}, "next_id": 1}
    return {"videos": {}, "next_id": 1}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        logger.error(f"ডাটা সেভ করতে ব্যর্থ: {e}")

# --- শিডিউলড ডিলিট ফাংশন ---
async def delete_scheduled_message(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data['chat_id']
    message_id = job_data['message_id']
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"মেসেজ ডিলিট সফল: Chat ID {chat_id}, Message ID {message_id}")
    except Exception as e:
        logger.warning(f"মেসেজ ডিলিট করতে ব্যর্থ: Chat ID {chat_id}, Message ID {message_id}. ত্রুটি: {e}")

# --- এডমিন আপলোড শুরু ---
async def start_upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id != ADMIN_USER_ID:
        return
    if user_id in STAGED_UPLOADS:
        del STAGED_UPLOADS[user_id]
    await update.message.reply_text("আপলোড শুরু হয়েছে। প্রথমত, অনুগ্রহ করে থাম্বনেইল ফটো আপলোড করুন।")

# --- এডমিন ফটো আপলোড হ্যান্ডলার ---
async def handle_admin_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id != ADMIN_USER_ID or not update.message.photo:
        return
    photo_file_id = update.message.photo[-1].file_id
    STAGED_UPLOADS[user_id] = {'photo_id': photo_file_id, 'photo_msg_id': update.message.message_id}
    await update.message.reply_text("ছবিটি সেভ হয়েছে। এবার ভিডিওটি আপলোড করুন।")

# --- এডমিন ভিডিও আপলোড হ্যান্ডলার ---
async def handle_admin_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    if user_id != ADMIN_USER_ID:
        return
    if user_id not in STAGED_UPLOADS or not update.message.video:
        if update.message.video and user_id not in STAGED_UPLOADS:
            await update.message.reply_text("ভিডিওটি আপলোড করার আগে /start_upload কমান্ড দিয়ে থাম্বনেইল আপলোড করুন।")
        return
    
    staged_data = STAGED_UPLOADS.pop(user_id)
    data = load_data()
    permanent_id = data["next_id"]
    video_file_id = update.message.video.file_id
    photo_file_id = staged_data['photo_id']
    
    data["videos"][str(permanent_id)] = {"video_id": video_file_id, "photo_id": photo_file_id}
    data["next_id"] += 1
    save_data(data)
    logger.info(f"নতুন ভিডিও সেভ হলো: ID {permanent_id}")

    # শেয়ারযোগ্য লিংক তৈরি করা
    payload_to_encode = f"VID_{permanent_id}"  
    encoded_payload = base64.urlsafe_b64encode(payload_to_encode.encode('utf-8')).decode('utf-8').rstrip('=')  
    shareable_link = f"https://t.me/{BOT_USERNAME}?start={encoded_payload}"  
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔥 ভিডিও দেখুন 🥵", url=shareable_link)]])  

    channel_caption = """\
╭═══════════════════
╠ ‣ দেশি ভিডিও ‣
╰═══════════════════
"""

    try:  
        await context.bot.send_photo(chat_id=CHANNEL_ID, photo=photo_file_id, caption=channel_caption, reply_markup=keyboard)  
        logger.info(f"চ্যানেলে পোস্ট সফল: Channel ID {CHANNEL_ID}, Permanent ID {permanent_id}")  
    except Exception as e:  
        logger.error(f"চ্যানেলে পোস্ট করতে ব্যর্থ: {e}")  
        await update.message.reply_text(f"❌ চ্যানেলে পোস্ট ব্যর্থ হয়েছে। ত্রুটি: {e}")  
        return  

    try:  
        await update.message.delete()  
        await context.bot.delete_message(chat_id=user_id, message_id=staged_data['photo_msg_id'])  
    except Exception as e:  
        logger.warning(f"এডমিন মেসেজ ডিলিট করতে ব্যর্থ: {e}")  

    await update.message.reply_text(f"✅ সফলভাবে পোস্ট হয়েছে। স্থায়ী আইডি: {permanent_id}")

# --- ইউজার /start কমান্ড ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("স্বাগতম! ভিডিও দেখার জন্য চ্যানেলের '🔥 ভিডিও দেখুন 🥵' বাটনে ক্লিক করুন।")
        return
        
    try:
        encoded_payload = context.args[0]
        # Base64 ডিকোডিং এর জন্য প্যাডিং নিশ্চিত করা
        padded_payload = encoded_payload + '=' * (4 - len(encoded_payload) % 4)
        decoded_payload = base64.urlsafe_b64decode(padded_payload.encode('utf-8')).decode('utf-8')

        if decoded_payload.startswith("VID_"):
            permanent_id = decoded_payload.split("VID_")[1]
            data = load_data()
            video_data = data["videos"].get(permanent_id)

            if video_data and video_data.get("video_id"):
                video_file_id = video_data["video_id"]
                sent_message = await update.message.reply_video(video=video_file_id, caption="🔥Successfull🥵")

                if update.message.from_user.id != ADMIN_USER_ID:
                    # ৪ ঘন্টা পর ডিলিট করার জন্য শিডিউল করা
                    context.job_queue.run_once(delete_scheduled_message, when=DELETION_TIME_SECONDS,
                                            data={'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id})
                    logger.info(f"ভিডিও ডিলিট শিডিউল করা হলো: ID {permanent_id}")
                else:
                    logger.info(f"এডমিন হওয়ায় ডিলিট শিডিউল করা হলো না: ID {permanent_id}")
                return
            
            await update.message.reply_text("দুঃখিত, এই ভিডিওটির ফাইল খুঁজে পাওয়া যায়নি।")
            
    except Exception as e:
        logger.error(f"স্টার্ট কমান্ড প্রসেস করতে ব্যর্থ: {e}")
        await update.message.reply_text("দুঃখিত, লিংকে কোনো সমস্যা আছে।")


# --- মেইন ফাংশন ---
def main() -> None:
    # কনফিগারেশন ত্রুটি হ্যান্ডলিং
    if not BOT_TOKEN or ADMIN_USER_ID == 0 or CHANNEL_ID == 0:
        logger.error("🛑 গুরুতর কনফিগারেশন ত্রুটি: BOT_TOKEN, ADMIN_USER_ID, বা CHANNEL_ID Environment Variables এ সেট করা নেই বা অবৈধ মান রয়েছে।")
        print("🛑 গুরুতর কনফিগারেশন ত্রুটি: Railway Variables চেক করুন।")
        return

    logging.getLogger('httpx').setLevel(logging.WARNING)
    application = Application.builder().token(BOT_TOKEN).build()

    # হ্যান্ডলার যুক্ত করা
    application.add_handler(CommandHandler("start", start_command))  
    application.add_handler(CommandHandler("start_upload", start_upload_command))  
    application.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_USER_ID) & (~filters.COMMAND), handle_admin_photo_upload))  
    application.add_handler(MessageHandler(filters.VIDEO & filters.User(ADMIN_USER_ID) & (~filters.COMMAND), handle_admin_video_upload))  

    print("🔥 বট চালু হয়েছে — এডমিন এখন /start_upload কমান্ড দিয়ে থাম্বনেইল ও ভিডিও আপলোড করতে পারবেন।")  
    application.run_polling(poll_interval=3.0)

if __name__ == "__main__":
    main()    if user_id not in STAGED_UPLOADS or STAGED_UPLOADS[user_id]['step'] != 'photo':
        await update.message.reply_text("ছবি আপলোড করার আগে /start_upload বা /start_upload_N কমান্ড দিয়ে আপলোড প্রক্রিয়া শুরু করুন।")
        return

    photo_file_id = update.message.photo[-1].file_id
    STAGED_UPLOADS[user_id]['photo_id'] = photo_file_id
    STAGED_UPLOADS[user_id]['photo_msg_id'] = update.message.message_id
    STAGED_UPLOADS[user_id]['step'] = 'video'
    
    count = STAGED_UPLOADS[user_id]['video_count']
    await update.message.reply_text(f"ছবিটি সেভ হয়েছে। এবার, অনুগ্রহ করে **ধারাবাহিকভাবে {count}টি ভিডিও** আপলোড করুন।")

# --- এডমিন ভিডিও আপলোড হ্যান্ডলার ---
async def handle_admin_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """এডমিনের পাঠানো ভিডিওগুলো সংগ্রহ করে এবং সব ভিডিও সংগ্রহ হলে চ্যানেলে পোস্ট করে"""
    user_id = update.message.from_user.id
    if user_id != ADMIN_USER_ID or not update.message.video:
        return
    
    if user_id not in STAGED_UPLOADS or STAGED_UPLOADS[user_id]['step'] != 'video':
        # যদি ভিডিও আসে কিন্তু আপলোড প্রক্রিয়া শুরু হয়নি
        if update.message.video and user_id not in STAGED_UPLOADS:
            await update.message.reply_text("ভিডিও আপলোড করার আগে /start_upload কমান্ড দিয়ে শুরু করুন।")
        return

    staged_data = STAGED_UPLOADS[user_id]
    video_file_id = update.message.video.file_id
    staged_data['video_ids'].append(video_file_id)
    
    current_count = len(staged_data['video_ids'])
    required_count = staged_data['video_count']
    
    await update.message.reply_text(f"ভিডিও সেভ হলো: {current_count} / {required_count}")

    # সব ভিডিও সংগ্রহ হয়ে গেলে
    if current_count == required_count:
        data = load_data()
        permanent_id = data["next_id"]
        
        # ডাটা সেভ করা
        data["videos"][str(permanent_id)] = {
            "video_ids": staged_data['video_ids'], 
            "photo_id": staged_data['photo_id']
        }
        data["next_id"] += 1
        save_data(data)
        logger.info(f"নতুন মাল্টিপল ভিডিও সেভ হলো: ID {permanent_id}, Count: {required_count}")

        # --- শেয়ারযোগ্য লিংক তৈরি করা ---
        payload_to_encode = f"VID_{permanent_id}"  
        encoded_payload = base64.urlsafe_b64encode(payload_to_encode.encode('utf-8')).decode('utf-8').rstrip('=')  
        shareable_link = f"https://t.me/{BOT_USERNAME}?start={encoded_payload}"  
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔥 ভিডিও দেখুন 🥵", url=shareable_link)]])  

        # *** ক্যাপশন টেক্সট সরলীকরণ করা হলো (এখানেই Syntax Error ছিল) ***
        channel_caption = f"""\
---
🔥 নতুন {required_count} টি ভিডিও 🔥
---
"""

        # চ্যানেলে থাম্বনেইল সহ পোস্ট করা
        try:  
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=staged_data['photo_id'], caption=channel_caption, reply_markup=keyboard)  
            logger.info(f"চ্যানেলে পোস্ট সফল: Permanent ID {permanent_id}")  
        except Exception as e:  
            logger.error(f"চ্যানেলে পোস্ট করতে ব্যর্থ: {e}")  
            await update.message.reply_text(f"❌ চ্যানেলে পোস্ট ব্যর্থ হয়েছে। ত্রুটি: {e}")  
            return  

        # এডমিনের মেসেজ ডিলিট করা
        try:  
            # এখানে শুধু ভিডিও মেসেজ ডিলিট হচ্ছে, photo_msg_id অন্য জায়গায় সেভ করা আছে
            await update.message.delete()  
            await context.bot.delete_message(chat_id=user_id, message_id=staged_data['photo_msg_id'])
        except Exception as e:  
            logger.warning(f"এডমিন মেসেজ ডিলিট করতে ব্যর্থ: {e}")  

        await update.message.reply_text(f"✅ সফলভাবে {required_count}টি ভিডিও পোস্ট হয়েছে। স্থায়ী আইডি: {permanent_id}")
        del STAGED_UPLOADS[user_id] # আপলোড প্রক্রিয়া শেষ
        
# --- ইউজার /start কমান্ড (লকড/আনলকড ভিডিও প্লেয়ার) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ইউজার যখন শেয়ার করা লিংকে ক্লিক করে তখন ভিডিওগুলো লক বা আনলকড অবস্থায় পাঠায়"""
    if not update.message:
        return

    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    
    # 1. payload যাচাই
    if not context.args:
        await update.message.reply_text("স্বাগতম! ভিডিও দেখার জন্য চ্যানেলের '🔥 ভিডিও দেখুন 🥵' বাটনে ক্লিক করুন।")
        return
        
    encoded_payload = context.args[0]
    padded_payload = encoded_payload + '=' * (4 - len(encoded_payload) % 4)
    
    try:
        decoded_payload = base64.urlsafe_b64decode(padded_payload.encode('utf-8')).decode('utf-8')
        if not decoded_payload.startswith("VID_") and not decoded_payload.startswith("UNLOCK_"):
            raise ValueError
    except Exception:
        await update.message.reply_text("দুঃখিত, লিংকে কোনো সমস্যা আছে।")
        return
    
    # payload থেকে পার্মানেন্ট ID বের করা
    if decoded_payload.startswith("VID_"):
        permanent_id = decoded_payload.split("VID_")[1]
        is_unlocked = False # VID_ মানেই লকড অবস্থায় আছে
    elif decoded_payload.startswith("UNLOCK_"):
        permanent_id = decoded_payload.split("UNLOCK_")[1]
        is_unlocked = True # UNLOCK_ মানে অ্যাড দেখে ফিরে এসেছে


    data = load_data()
    video_data = data["videos"].get(permanent_id)

    if not video_data or not video_data.get("video_ids"):
        await update.message.reply_text("দুঃখিত, এই ভিডিওটির ফাইল খুঁজে পাওয়া যায়নি।")
        return

    video_ids = video_data['video_ids']
    
    # 2. ভিডিও লক অবস্থায় পাঠানো (ছবি সহ বাটন)
    if not is_unlocked and user_id != ADMIN_USER_ID:
        
        # Base64 দিয়ে UNLOCK_ কী তৈরি করা
        lock_key = base64.urlsafe_b64encode(f"UNLOCK_{permanent_id}".encode('utf-8')).decode('utf-8').rstrip('=')
        
        # ইউজারকে অ্যাড দেখতে পাঠানোর বাটন
        ad_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 অ্যাড দেখুন এবং ভিডিও আনলক করুন", url=f"{AD_URL}")
        ]])
        
        # আনলক করার জন্য একটি বাটন
        unlock_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ আনলক করুন এবং ভিডিও দেখুন", url=f"https://t.me/{BOT_USERNAME}?start={lock_key}")
        ]])

        locked_caption = f"🚨 ভিডিও লকড! 🚨\n\nভিডিওগুলো আনলক করতে নিচের বাটনে ক্লিক করে অ্যাডটি দেখুন।\n\nভিডিও সংখ্যা: {len(video_ids)}"
        
        try:
            # থাম্বনেইল সহ লকড মেসেজ পাঠানো
            sent_message = await update.message.reply_photo(
                photo=video_data['photo_id'], 
                caption=locked_caption, 
                reply_markup=ad_keyboard
            )
            context.job_queue.run_once(delete_scheduled_message, when=DELETION_TIME_SECONDS,
                                    data={'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id})
        except Exception as e:
            logger.error(f"লকড মেসেজ/ছবি পাঠাতে ব্যর্থ: {e}")
            await update.message.reply_text("ভিডিও লকড। আনলক করতে নিচের লিংকে যান।", reply_markup=ad_keyboard)
        
        await update.message.reply_text("ওয়েবসাইট থেকে অ্যাড দেখে আসার পর নিচের বাটনটি ক্লিক করুন:", reply_markup=unlock_keyboard)

        logger.info(f"লকড ভিডিও পাঠানো হলো: ID {permanent_id} to User {user_id}")
        return

    # 3. ভিডিও আনলকড/এডমিন হলে
    
    # ভিডিওগুলো MediaGroup হিসেবে পাঠানো হচ্ছে
    media_group = []
    for i, file_id in enumerate(video_ids):
        # প্রথম ভিডিওতে ক্যাপশন দেওয়া হচ্ছে
        caption = f"🎬 ভিডিও {i+1} / {len(video_ids)}" if i == 0 else ""
        media_group.append(InputMediaVideo(media=file_id, caption=caption))
        
    try:
        # সফলভাবে আনলক হওয়ার মেসেজ
        if is_unlocked and user_id != ADMIN_USER_ID:
            await update.message.reply_text("✅ আনলক সফল! নিচে আপনার ভিডিওগুলো দেখা যাচ্ছে।", reply_markup=telegram.ReplyKeyboardRemove())


        sent_messages = await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        logger.info(f"আনলকড ভিডিও পাঠানো সফল: ID {permanent_id} to User {user_id}")

        if user_id != ADMIN_USER_ID:
            # সব মেসেজ ৪ ঘন্টা পর ডিলিট করার জন্য শিডিউল করা
            for sent_message in sent_messages:
                context.job_queue.run_once(delete_scheduled_message, when=DELETION_TIME_SECONDS,
                                        data={'chat_id': sent_message.chat_id, 'message_id': sent_message.message_id})
    except Exception as e:
        logger.error(f"MediaGroup পাঠাতে ব্যর্থ: {e}")
        await update.message.reply_text("ভিডিও পাঠাতে সমস্যা হয়েছে।")


# --- মেইন ফাংশন ---
def main() -> None:
    """বট অ্যাপ্লিকেশন চালু করে"""
    if not BOT_TOKEN or ADMIN_USER_ID == 0 or CHANNEL_ID == 0 or not AD_URL:
        logger.error("🛑 গুরুতর কনফিগারেশন ত্রুটি: Environment Variables চেক করুন (BOT_TOKEN, ADMIN_USER_ID, CHANNEL_ID, AD_URL)।")
        print("🛑 গুরুতর কনফিগারেশন ত্রুটি: Railway Variables চেক করুন।")
        return

    logging.getLogger('httpx').setLevel(logging.WARNING)
    application = Application.builder().token(BOT_TOKEN).build()

    # কমান্ড হ্যান্ডলার
    application.add_handler(CommandHandler("start", start_command))
    # /start_upload_N অথবা /start_upload কমান্ড হ্যান্ডেল করার জন্য regex ব্যবহার
    application.add_handler(CommandHandler(re.compile(r"start_upload_\d+|start_upload"), start_upload_command))
      
    # এডমিন মেসেজ হ্যান্ডলার
    # ফটো হ্যান্ডলার
    application.add_handler(MessageHandler(
        filters.PHOTO & filters.User(ADMIN_USER_ID) & (~filters.COMMAND), 
        handle_admin_photo_upload
    ))  
    # ভিডিও হ্যান্ডলার
    application.add_handler(MessageHandler(
        filters.VIDEO & filters.User(ADMIN_USER_ID) & (~filters.COMMAND), 
        handle_admin_video_upload
    ))  

    print(f"🔥 বট চালু হয়েছে — এডমিন এখন /start_upload_N কমান্ড দিয়ে {AD_URL} এ অ্যাড দেখে মাল্টিপল ভিডিও আপলোড করতে পারবেন।")  
    application.run_polling(poll_interval=3.0)

if __name__ == "__main__":
    main()
