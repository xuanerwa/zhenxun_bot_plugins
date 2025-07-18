import asyncio
import httpx
import nonebot
import random
from asyncio.exceptions import TimeoutError
from bilireq.exceptions import ResponseCodeError
from datetime import datetime, timedelta
from zhenxun.configs.config import Config
from zhenxun.configs.path_config import IMAGE_PATH
from zhenxun.services.log import logger
from zhenxun.utils._build_image import BuildImage
from zhenxun.utils.http_utils import AsyncHttpx
from zhenxun.utils.platform import PlatformUtils
from zhenxun.utils.utils import ResourceDirManager

from .filter import check_page_elements
from .model import BilibiliSub
from .utils import (
    get_dynamic_screenshot,
    get_meta,
    get_room_info_by_id,
    get_user_card,
    get_user_dynamics,
    get_videos,
)

base_config = Config.get("bilibili_sub")

SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/all/v2"

DYNAMIC_PATH = IMAGE_PATH / "bilibili_sub" / "dynamic"
DYNAMIC_PATH.mkdir(exist_ok=True, parents=True)

ResourceDirManager.add_temp_dir(DYNAMIC_PATH)


# 获取图片bytes
async def fetch_image_bytes(url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()  # 检查响应状态码是否为200
        return response.content


async def handle_video_info_error(video_info: dict):
    """

    处理B站视频信息获取错误并发送通知给超级用户
    :param video_info: 包含错误信息的字典
    :param platform_utils: 用于发送消息的工具类
    """
    str_msg = "b站订阅检测失败："
    if video_info["code"] == -352:
        str_msg += "风控校验失败，请登录后再尝试。发送'登录b站'"
    elif video_info["code"] == -799:
        str_msg += "请求过于频繁，请增加时长，更改配置文件下的'CHECK_TIME''"
    else:
        str_msg += f"{video_info['code']}，{video_info['message']}"

    bots = nonebot.get_bots()
    for bot in bots.values():
        if bot:
            await PlatformUtils.send_superuser(bot, str_msg)

    return str_msg


async def add_live_sub(live_id: int, sub_user: str) -> str:
    """

    添加直播订阅
    :param live_id: 直播房间号
    :param sub_user: 订阅用户 id # 7384933:private or 7384933:2342344(group)
    :return:
    """
    try:
        try:
            """bilibili_api.live库的LiveRoom类中get_room_info改为bilireq.live库的get_room_info_by_id方法"""
            live_info = await get_room_info_by_id(live_id)
        except ResponseCodeError:
            return f"未找到房间号Id：{live_id} 的信息，请检查Id是否正确"
        uid = live_info["uid"]
        room_id = live_info["room_id"]
        short_id = live_info["short_id"]
        title = live_info["title"]
        live_status = live_info["live_status"]
        if await BilibiliSub.sub_handle(
            room_id,
            "live",
            sub_user,
            uid=uid,
            live_short_id=short_id,
            live_status=live_status,
        ):
            await _get_up_status(room_id)
            uname = (await BilibiliSub.get_or_none(sub_id=room_id)).uname
            return (
                "订阅成功！🎉\n"
                f"主播名称：{uname}\n"
                f"直播标题：{title}\n"
                f"直播间ID：{room_id}\n"
                f"用户UID：{uid}"
            )
        else:
            return "添加订阅失败..."
    except Exception as e:
        logger.error(f"订阅主播live_id：{live_id} 发生了错误 {type(e)}：{e}")
    return "添加订阅失败..."


async def add_up_sub(uid: int, sub_user: str) -> str:
    """
    添加订阅 UP
    :param uid: UP uid
    :param sub_user: 订阅用户
    """
    try:
        try:
            """bilibili_api.user库中User类的get_user_info改为bilireq.user库的get_user_info方法"""
            user_info = await get_user_card(uid)
        except ResponseCodeError:
            return f"未找到UpId：{uid} 的信息，请检查Id是否正确"
        uname = user_info["name"]
        try:
            dynamic_info = await get_user_dynamics(uid)
        except ResponseCodeError as e:
            if e.code == -352:
                return "风控校验失败，请联系管理员登录b站'"
            return "添加订阅失败..."
        dynamic_upload_time = 0
        if dynamic_info.get("cards"):
            dynamic_upload_time = dynamic_info["cards"][0]["desc"]["timestamp"]
        """bilibili_api.user库中User类的get_videos改为bilireq.user库的get_videos方法"""
        video_info = await get_videos(uid)
        if not video_info.get("data"):
            await handle_video_info_error(video_info)
            return "订阅失败，请联系管理员"
        else:
            video_info = video_info["data"]
        latest_video_created = 0
        if video_info["list"].get("vlist"):
            latest_video_created = video_info["list"]["vlist"][0]["created"]
        if await BilibiliSub.sub_handle(
            uid,
            "up",
            sub_user,
            uid=uid,
            uname=uname,
            dynamic_upload_time=dynamic_upload_time,
            latest_video_created=latest_video_created,
        ):
            return f"订阅成功！🎉\nUP主名称：{uname}\n用户UID：{uid}"
        else:
            return "添加订阅失败..."
    except Exception as e:
        logger.error(f"订阅Up uid：{uid} 发生了错误 {type(e)}：{e}")
    return "添加订阅失败..."


async def add_season_sub(media_id: int, sub_user: str) -> str:
    """
    添加订阅 UP
    :param media_id: 番剧 media_id
    :param sub_user: 订阅用户
    """
    try:
        try:
            """bilibili_api.bangumi库中get_meta改为bilireq.bangumi库的get_meta方法"""
            season_info = await get_meta(media_id)
        except ResponseCodeError:
            return f"未找到media_id：{media_id} 的信息，请检查Id是否正确"
        season_id = season_info["media"]["season_id"]
        season_current_episode = season_info["media"]["new_ep"]["index"]
        season_name = season_info["media"]["title"]
        if await BilibiliSub.sub_handle(
            media_id,
            "season",
            sub_user,
            season_name=season_name,
            season_id=season_id,
            season_current_episode=season_current_episode,
        ):
            return (
                "订阅成功！🎉\n"
                f"番剧名称：{season_name}\n"
                f"当前集数：{season_current_episode}"
            )
        else:
            return "添加订阅失败..."
    except Exception as e:
        logger.error(f"订阅番剧 media_id：{media_id} 发生了错误 {type(e)}：{e}")
    return "添加订阅失败..."


async def delete_sub(sub_id: str, sub_user: str) -> str:
    """
    删除订阅
    :param sub_id: 订阅 id
    :param sub_user: 订阅用户 id # 7384933:private or 7384933:2342344(group)
    """
    if await BilibiliSub.delete_bilibili_sub(int(sub_id), sub_user):
        return f"已成功取消订阅：{sub_id}"
    else:
        return f"取消订阅：{sub_id} 失败，请检查是否订阅过该Id...."


async def get_media_id(keyword: str) -> dict:
    """
    获取番剧的 media_id
    :param keyword: 番剧名称
    """
    from .auth import AuthManager

    params = {"keyword": keyword}
    for _ in range(3):
        try:
            _season_data = {}
            response = await AsyncHttpx.get(
                SEARCH_URL, params=params, cookies=AuthManager.get_cookies(), timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("data"):
                    for item in data["data"]["result"]:
                        if item["result_type"] == "media_bangumi":
                            idx = 0
                            for x in item["data"]:
                                _season_data[idx] = {
                                    "media_id": x["media_id"],
                                    "title": x["title"]
                                    .replace('<em class="keyword">', "")
                                    .replace("</em>", ""),
                                }
                                idx += 1
                            return _season_data
        except TimeoutError:
            pass
        return {}


async def get_sub_status(id_: int, sub_type: str) -> list | None:
    """
    获取订阅状态
    :param id_: 订阅 id
    :param sub_type: 订阅类型
    """
    try:
        if sub_type == "live":
            return await _get_live_status(id_)
        elif sub_type == "up":
            return await _get_up_status(id_)
        elif sub_type == "season":
            return await _get_season_status(id_)
    except ResponseCodeError as msg:
        logger.error(f"Id：{id_} 获取信息失败...{msg}")
        return None


async def _get_live_status(id_: int) -> list:
    """
    获取直播订阅状态
    :param id_: 直播间 id
    """
    """bilibili_api.live库的LiveRoom类中get_room_info改为bilireq.live库的get_room_info_by_id方法"""
    live_info = await get_room_info_by_id(id_)
    title = live_info["title"]
    room_id = live_info["room_id"]
    live_status = live_info["live_status"]
    cover = live_info["user_cover"]
    sub = await BilibiliSub.get_or_none(sub_id=id_)
    msg_list = []
    if sub.live_status != live_status:
        await BilibiliSub.sub_handle(id_, live_status=live_status)
        image = None
        try:
            image_bytes = await fetch_image_bytes(cover)
            image = BuildImage(background=image_bytes)
        except Exception as e:
            logger.error(f"图片构造失败，错误信息：{e}")
    if sub.live_status in [0, 2] and live_status == 1 and image:
        msg_list = [
            image,
            "\n",
            f"{sub.uname} 开播啦！🎉\n",
            f"标题：{title}\n",
            f"直播间链接：https://live.bilibili.com/{room_id}",
        ]
    return msg_list


async def fetch_image_with_retry(url, retries=3, delay=2):
    """带重试的图片获取函数"""
    for i in range(retries):
        try:
            return await fetch_image_bytes(url)
        except Exception as e:
            if i < retries - 1:
                await asyncio.sleep(delay)
            else:
                raise e
    return None


async def _get_up_status(id_: int) -> list:
    # 获取当前时间戳
    current_time = datetime.now()

    _user = await BilibiliSub.get_or_none(sub_id=id_)
    user_info = await get_user_card(_user.uid)
    uname = user_info["name"]

    # 获取用户视频信息
    video_info = await get_videos(_user.uid)
    if not video_info.get("data"):
        await handle_video_info_error(video_info)
        return []
    video_info = video_info["data"]

    # 初始化消息列表和时间阈值（30分钟）
    msg_list = []
    time_threshold = current_time - timedelta(minutes=30)
    dividing_line = "\n-------------\n"

    # 处理用户名更新
    if _user.uname != uname:
        await BilibiliSub.sub_handle(id_, uname=uname)

    # 处理动态信息
    dynamic_img = None
    try:
        dynamic_img, dynamic_upload_time, link = await get_user_dynamic(
            _user.uid, _user
        )
    except ResponseCodeError as msg:
        logger.error(f"Id：{id_} 动态获取失败...{msg}")

    # 动态时效性检查
    if dynamic_img and _user.dynamic_upload_time < dynamic_upload_time:
        dynamic_time = datetime.fromtimestamp(dynamic_upload_time)
        logger.info(link)
        if dynamic_time > time_threshold:  # 30分钟内动态
            # 检查动态是否含广告
            if base_config.get("SLEEP_END_TIME"):
                if await check_page_elements(link):
                    await BilibiliSub.sub_handle(
                        id_, dynamic_upload_time=dynamic_upload_time
                    )
                    return msg_list  # 停止执行

            await BilibiliSub.sub_handle(id_, dynamic_upload_time=dynamic_upload_time)
            msg_list = [f"{uname} 发布了动态！📢\n", dynamic_img, f"\n查看详情：{link}"]
        else:  # 超过30分钟仍更新时间戳避免重复处理
            await BilibiliSub.sub_handle(id_, dynamic_upload_time=dynamic_upload_time)

    # 处理视频信息
    video = None
    if video_info["list"].get("vlist"):
        video = video_info["list"]["vlist"][0]
        latest_video_created = video.get("created", "")

        # 视频时效性检查
        if (
            latest_video_created
            and _user.latest_video_created < latest_video_created
            and datetime.fromtimestamp(latest_video_created) > time_threshold
        ):
            # 检查视频链接是否被拦截
            video_url = f"https://www.bilibili.com/video/{video['bvid']}"

            # 带重试的封面获取
            image = None
            try:
                image_bytes = await fetch_image_with_retry(
                    video["pic"], retries=3, delay=2
                )
                image = BuildImage(background=image_bytes)
            except Exception as e:
                logger.error(f"封面获取失败（已重试3次）: {e}")

            # 构建消息内容
            video_msg = [
                f"{uname} 投稿了新视频啦！🎉\n",
                f"标题：{video['title']}\n",
                f"Bvid：{video['bvid']}\n",
                f"链接：{video_url}",
            ]

            # 合并动态和视频消息
            if msg_list and image:
                msg_list += [dividing_line, image] + video_msg
            elif image:  # 仅有视频更新
                msg_list = [image] + video_msg
            elif msg_list:  # 有动态但无封面
                msg_list += [dividing_line] + video_msg
            else:  # 仅有无封面视频
                msg_list = ["⚠️ 封面获取失败，但仍需通知："] + video_msg

            # 强制更新视频时间戳
            await BilibiliSub.sub_handle(id_, latest_video_created=latest_video_created)

        elif latest_video_created > _user.latest_video_created:  # 超时视频仍更新时间戳
            await BilibiliSub.sub_handle(id_, latest_video_created=latest_video_created)

    return msg_list


async def _get_season_status(id_) -> list:
    """
    获取 番剧 更新状态
    :param id_: 番剧 id
    """
    """bilibili_api.bangumi库中get_meta改为bilireq.bangumi库的get_meta方法"""
    season_info = await get_meta(id_)
    title = season_info["media"]["title"]
    _idx = (await BilibiliSub.get_or_none(sub_id=id_)).season_current_episode
    new_ep = season_info["media"]["new_ep"]["index"]
    msg_list = []
    if new_ep != _idx:
        image = None
        try:
            image_bytes = await fetch_image_bytes(season_info["media"]["cover"])
            image = BuildImage(background=image_bytes)
        except Exception as e:
            logger.error(f"图片构造失败，错误信息：{e}")
        if image:
            await BilibiliSub.sub_handle(
                id_, season_current_episode=new_ep, season_update_time=datetime.now()
            )
            msg_list = [
                image,
                "\n",
                f"[{title}] 更新啦！🎉\n",
                f"最新集数：{new_ep}",
            ]
    return msg_list


async def get_user_dynamic(
    uid: int, local_user: BilibiliSub
) -> tuple[bytes | None, int, str]:
    """
    获取用户动态
    :param uid: 用户uid
    :param local_user: 数据库存储的用户数据
    :return: 最新动态截图与时间
    """
    try:
        dynamic_info = await get_user_dynamics(uid)
    except Exception:
        return None, 0, ""
    if dynamic_info:
        if dynamic_info.get("cards"):
            dynamic_upload_time = dynamic_info["cards"][0]["desc"]["timestamp"]
            dynamic_id = dynamic_info["cards"][0]["desc"]["dynamic_id"]
            if local_user.dynamic_upload_time < dynamic_upload_time:
                image = await get_dynamic_screenshot(dynamic_id)
                return (
                    image,
                    dynamic_upload_time,
                    f"https://t.bilibili.com/{dynamic_id}",
                )
    return None, 0, ""


class SubManager:
    def __init__(self):
        self.live_data = []
        self.up_data = []
        self.season_data = []
        self.current_index = -1

    async def reload_sub_data(self):
        """
        重载数据
        """
        # 如果 live_data、up_data 和 season_data 全部为空，重新加载所有数据
        if not (self.live_data and self.up_data and self.season_data):
            (
                self.live_data,
                self.up_data,
                self.season_data,
            ) = await BilibiliSub.get_all_sub_data()

    async def random_sub_data(self) -> BilibiliSub | None:
        """
        随机获取一条数据，保证所有 data 都轮询一次后再重载
        :return: Optional[BilibiliSub]
        """
        sub = None

        # 计算所有数据的总量，确保所有数据轮询完毕后再考虑重载
        total_data = sum(
            [len(self.live_data), len(self.up_data), len(self.season_data)]
        )

        # 如果所有列表都为空，重新加载一次数据以保证数据库非空
        if total_data == 0:
            await self.reload_sub_data()
            total_data = sum(
                [len(self.live_data), len(self.up_data), len(self.season_data)]
            )
            if total_data == 0:
                return sub

        attempts = 0

        # 开始轮询，直到所有数据都被遍历一次
        while attempts < total_data:
            self.current_index = (self.current_index + 1) % 3  # 轮询 0, 1, 2 之间

            # 根据 current_index 从相应的列表中随机取出数据
            if self.current_index == 0 and self.live_data:
                sub = random.choice(self.live_data)
                self.live_data.remove(sub)
                attempts += 1  # 成功从 live_data 获取数据
            elif self.current_index == 1 and self.up_data:
                sub = random.choice(self.up_data)
                self.up_data.remove(sub)
                attempts += 1  # 成功从 up_data 获取数据
            elif self.current_index == 2 and self.season_data:
                sub = random.choice(self.season_data)
                self.season_data.remove(sub)
                attempts += 1  # 成功从 season_data 获取数据

            # 如果成功找到数据，立即返回
            if sub:
                return sub
