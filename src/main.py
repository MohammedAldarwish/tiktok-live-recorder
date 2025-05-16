# print banner
from utils.utils import banner
banner()


import asyncio


# check and install dependencies
from utils.dependencies import check_and_install_dependencies
check_and_install_dependencies()

from check_updates import check_updates

import sys
import os
import threading
import signal
import time

from utils.args_handler import validate_and_parse_args
from utils.utils import read_cookies
from utils.logger_manager import logger
from upload.telegram import Telegram

from core.tiktok_recorder import TikTokRecorder
from utils.custom_exceptions import UserLiveException

from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

stop_event = threading.Event()

def signal_handler(sig, frame):
    print("\n[!] Ctrl+C detected. Stopping all recordings...")
    stop_event.set()

signal.signal(signal.SIGINT, signal_handler)

def read_users_from_file(filename="users.txt"):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logger.error(f"File {filename} not found.")
        return []

def is_user_live(user, args, mode, cookies):
    try:
        rec = TikTokRecorder(
            user=user,
            url=None,
            room_id=None,
            mode=mode,
            automatic_interval=args.automatic_interval,
            cookies=cookies,
            proxy=args.proxy,
            output=None, 
            duration=1,  
            use_telegram=False,
            stop_event=threading.Event(),
        )
        rec.check_live_status()
        return True
    except UserLiveException:
        return False
    except Exception as e:
        logger.error(f"[!] Error checking live status for {user}: {e}")
        return False

def start_recording_for_user(user, args, mode, cookies, stop_event):
    asyncio.set_event_loop(asyncio.new_event_loop())
    output_filename = f"recordings/{user}_live_record.mp4"  
    TikTokRecorder(
        user=user,
        url=None,
        room_id=None,
        mode=mode,
        automatic_interval=args.automatic_interval,
        cookies=cookies,
        proxy=args.proxy,
        output=output_filename,
        duration=args.duration,
        use_telegram=args.telegram,
        stop_event=stop_event,
    ).run()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = (
        f"📴 <b>تم إنهاء البث</b>\n" # the live has ended
        f"👤 <b>المستخدم:</b> <code>{user}</code>\n" # user
        f"🎥 <b>الملف:</b> <code>{output_filename}</code>\n" # file
        f"🕒 <b>الوقت:</b> <code>{timestamp}</code>"# time
    )

    telegram = Telegram()
    telegram.send_message(message)
    
    # if args.telegram:
    #     telegram.upload(output_filename)

def main():
    args, mode = validate_and_parse_args()
    cookies = read_cookies()
    recorded_users = set()  

    print("[*] Starting 24/7 live monitor...")

    while not stop_event.is_set():
        users = read_users_from_file()
        print(f"[*] Checking live status for {len(users)} users...")

        for user in users:
            if stop_event.is_set():
                break

            if user not in recorded_users:
                print(f"[*] Checking user: {user}")

                if is_user_live(user, args, mode, cookies):
                    print(f"[+] {user} is live! Starting recording...")
                    t = threading.Thread(target=start_recording_for_user, args=(user, args, mode, cookies, stop_event))
                    t.start()
                    recorded_users.add(user)
                else:
                    print(f"[-] {user} is not live.")

            else:
                print(f"[=] Already recording {user}, skipping.")

        time.sleep(30)  

    print("[*] Stop event detected. Exiting...")


if __name__ == "__main__":
    main()


