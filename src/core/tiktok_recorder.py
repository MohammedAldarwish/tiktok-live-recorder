import os
import time
from http.client import HTTPException

from requests import RequestException

from core.tiktok_api import TikTokAPI
from utils.logger_manager import logger
from utils.video_management import VideoManagement
from upload.telegram import Telegram
from utils.custom_exceptions import LiveNotFound, UserLiveException, \
    TikTokException
from utils.enums import Mode, Error, TimeOut, TikTokError


class TikTokRecorder:

    def __init__(
        self,
        url,
        user,
        room_id,
        mode,
        automatic_interval,
        cookies,
        proxy,
        output,
        duration,
        use_telegram,
        stop_event=None,
    ):
        # Setup TikTok API client
        self.tiktok = TikTokAPI(proxy=proxy, cookies=cookies)

        # TikTok Data
        self.url = url
        self.user = user
        self.room_id = room_id

        # Tool Settings
        self.mode = mode
        self.automatic_interval = automatic_interval
        self.duration = duration
        self.output = output

        # Upload Settings
        self.use_telegram = use_telegram

        self.stop_event = stop_event


        # Check if the user's country is blacklisted
        self.check_country_blacklisted()

        # Get live information based on the provided user data
        if self.url:
            self.user, self.room_id = \
                self.tiktok.get_room_and_user_from_url(self.url)

        if not self.user:
            self.user = self.tiktok.get_user_from_room_id(self.room_id)

        if not self.room_id:
            self.room_id = self.tiktok.get_room_id_from_user(self.user)

        logger.info(f"USERNAME: {self.user}" + ("\n" if not self.room_id else ""))
        logger.info(f"ROOM_ID:  {self.room_id}" + ("\n" if not self.tiktok.is_room_alive(self.room_id) else ""))

        # If proxy is provided, set up the HTTP client without the proxy
        if proxy:
            self.tiktok = TikTokAPI(proxy=None, cookies=cookies)

    def run(self):
        """
        runs the program in the selected mode. 

        If the mode is MANUAL, it checks if the user is currently live and
        if so, starts recording.
        
        If the mode is AUTOMATIC, it continuously checks if the user is live
        and if not, waits for the specified timeout before rechecking.
        If the user is live, it starts recording.
        """
        if self.mode == Mode.MANUAL:
            self.manual_mode()

        if self.mode == Mode.AUTOMATIC:
            self.automatic_mode()

    def manual_mode(self):
        if not self.tiktok.is_room_alive(self.room_id):
            raise UserLiveException(
                f"@{self.user}: {TikTokError.USER_NOT_CURRENTLY_LIVE}"
            )

        self.start_recording()

    def automatic_mode(self):
        while not self.stop_event or not self.stop_event.is_set():
            try:
                self.room_id = self.tiktok.get_room_id_from_user(self.user)
                self.manual_mode()

            except UserLiveException as ex:
                logger.info(ex)
                logger.info(f"Waiting {self.automatic_interval} minutes before recheck\n")

                for _ in range(int(self.automatic_interval * 60)):
                    if self.stop_event and self.stop_event.is_set():
                        logger.info("Stop event detected during wait. Exiting automatic mode.")
                        return
                    time.sleep(1)

            except ConnectionError:
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                for _ in range(int(TimeOut.CONNECTION_CLOSED * 60)):
                    if self.stop_event and self.stop_event.is_set():
                        logger.info("Stop event detected during wait. Exiting automatic mode.")
                        return
                    time.sleep(1)

            except Exception as ex:
                logger.error(f"Unexpected error: {ex}\n")

        logger.info("Stop event detected. Exiting automatic mode.")

    def start_recording(self):
        """
        Start recording live
        """
        live_url = self.tiktok.get_live_url(self.room_id)
        if not live_url:
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        current_date = time.strftime("%Y.%m.%d_%H-%M-%S", time.localtime())

        if isinstance(self.output, str) and self.output != '':
            if not (self.output.endswith('/') or self.output.endswith('\\')):
                self.output += "\\" if os.name == 'nt' else "/"

        output = f"{self.output if self.output else ''}TK_{self.user}_{current_date}_flv.mp4"

        output_dir = os.path.dirname(output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        logger.info(f"Started recording for {self.duration} seconds " if self.duration else "Started recording...")
        buffer_size = 512 * 1024  # 512 KB
        buffer = bytearray()

        logger.info("[PRESS CTRL + C ONCE TO STOP]")

        try:
            with open(output, "wb") as out_file:
                stop_recording = False
                start_time = time.time()

                while not stop_recording:
                    # Check if user stopped manually
                    if self.stop_event and self.stop_event.is_set():
                        logger.info("Recording stopped by Ctrl+C.")
                        break

                    # Check if live ended
                    if not self.tiktok.is_room_alive(self.room_id):
                        logger.info("User is no longer live. Stopping recording.")
                        break

                    for chunk in self.tiktok.download_live_stream(live_url):
                        if self.stop_event and self.stop_event.is_set():
                            stop_recording = True
                            break

                        buffer.extend(chunk)
                        if len(buffer) >= buffer_size:
                            out_file.write(buffer)
                            buffer.clear()

                        if self.duration and (time.time() - start_time) >= self.duration:
                            stop_recording = True
                            break

                    time.sleep(0.1) 

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Stopping recording.")

        except ConnectionError:
            if self.mode == Mode.AUTOMATIC:
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                time.sleep(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

        except (RequestException, HTTPException):
            time.sleep(2)

        except Exception as ex:
            logger.error(f"Unexpected error: {ex}\n")

        finally:
            try:
                with open(output, "ab") as out_file:
                    if buffer:
                        out_file.write(buffer)
                    out_file.flush()
            except Exception as e:
                logger.error(f"Error while flushing buffer: {e}")

            logger.info(f"Recording finished: {output}\n")
            VideoManagement.convert_flv_to_mp4(output)

            if self.use_telegram:
                Telegram().upload(output.replace('_flv.mp4', '.mp4'))


    def check_country_blacklisted(self):
        is_blacklisted = self.tiktok.is_country_blacklisted()
        if not is_blacklisted:
            return False

        if self.room_id is None:
            raise TikTokException(TikTokError.COUNTRY_BLACKLISTED)

        if self.mode == Mode.AUTOMATIC:
            raise TikTokException(TikTokError.COUNTRY_BLACKLISTED_AUTO_MODE)
    

    def check_live_status(self):
        """
        Check if the user is currently live without starting recording.
        Raises UserLiveException if not live.
        """
        if not self.tiktok.is_room_alive(self.room_id):
            raise UserLiveException(f"@{self.user} is not live.")
