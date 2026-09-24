# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import logging
import requests
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkecs.request.v20140526 import StartInstancesRequest, StopInstancesRequest, DescribeInstancesRequest

# ================== 1. 配置日志 ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ================== 2. 读取本地配置文件 ==================
config_path = 'config.json'

if not os.path.exists(config_path):
    logger.error("❌ 找不到 config.json 文件，请参考 config.example.json 创建！")
    sys.exit(1)

try:
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
except Exception as e:
    logger.error(f"❌ 读取 config.json 失败，请检查 JSON 格式是否正确: {e}")
    sys.exit(1)

# ================== 3. 提取所有运行参数 ==================
# 阿里云配置
ACCESS_KEY_ID = config.get('ALIYUN_AK')
ACCESS_KEY_SECRET = config.get('ALIYUN_SK')
REGION_ID = config.get('REGION_ID', 'cn-hongkong')
ECS_INSTANCE_ID = config.get('ECS_INSTANCE_ID')

# TG 机器人配置
TG_BOT_TOKEN = config.get('TG_BOT_TOKEN')
TG_CHAT_ID = config.get('TG_CHAT_ID')

# 监控阈值配置
TRAFFIC_THRESHOLD_GB = config.get('TRAFFIC_THRESHOLD_GB', 180)
CHECK_INTERVAL_SECONDS = config.get('CHECK_INTERVAL_SECONDS', 1800)

if not all([ACCESS_KEY_ID, ACCESS_KEY_SECRET, ECS_INSTANCE_ID]):
    logger.error("❌ config.json 中缺少 ALIYUN_AK、ALIYUN_SK 或 ECS_INSTANCE_ID 等核心参数！")
    sys.exit(1)

# ================== 4. 初始化阿里云客户端 ==================
try:
    client = AcsClient(ACCESS_KEY_ID, ACCESS_KEY_SECRET, REGION_ID)
except Exception as e:
    logger.error(f"❌ 初始化 AcsClient 失败: {e}")
    sys.exit(1)

# ================== 5. 功能函数 ==================
def send_tg_message(text):
    """发送 Telegram 机器人通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.warning("未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过 TG 通知。")
        return

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        # 增加 timeout 防止网络阻塞挂起进程
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"TG 通知发送失败: {response.text}")
    except Exception as e:
        logger.error(f"TG 请求异常: {e}")

def get_total_traffic_gb():
    """获取 CDT 总互联网流量"""
    request = CommonRequest()
    request.set_domain('cdt.aliyuncs.com')
    request.set_version('2021-08-13')
    request.set_action_name('ListCdtInternetTraffic')
    request.set_method('POST')
    
    # 强制网络超时机制（单位：毫秒）
    request.set_connect_timeout(10000)
    request.set_read_timeout(10000)

    try:
        response = client.do_action_with_exception(request)
        response_json = json.loads(response.decode('utf-8'))
        total_bytes = sum(d.get('Traffic', 0) for d in response_json.get('TrafficDetails', []))
        return total_bytes / (1024 ** 3)
    except Exception as e:
        logger.error(f"获取CDT流量失败: {e}")
        return None

def get_ecs_status():
    """获取 ECS 实例运行状态"""
    try:
        request = DescribeInstancesRequest.DescribeInstancesRequest()
        request.set_InstanceIds([ECS_INSTANCE_ID])
        
        request.set_connect_timeout(10000)
        request.set_read_timeout(10000)

        response = client.do_action_with_exception(request)
        response_json = json.loads(response.decode('utf-8'))

        instances = response_json.get("Instances", {}).get("Instance", [])
        if not instances:
            return "NotFound"
        return instances[0].get("Status")
    except Exception as e:
        logger.error(f"获取ECS状态失败: {e}")
        return "Error"

def control_ecs(action, current_status):
    """控制 ECS 启停"""
    if action == "start":
        if current_status == "Running":
            return "✅ 机器运行中，无需操作"
        try:
            request = StartInstancesRequest.StartInstancesRequest()
            request.set_InstanceIds([ECS_INSTANCE_ID])
            request.set_connect_timeout(10000)
            request.set_read_timeout(10000)
            client.do_action_with_exception(request)
            return "🟢 已发送开机指令"
        except Exception as e:
            return f"❌ 开机失败: {e}"

    elif action == "stop":
        if current_status == "Stopped":
            return "💤 机器已关机，无需操作"
        try:
            request = StopInstancesRequest.StopInstancesRequest()
            request.set_InstanceIds([ECS_INSTANCE_ID])
            request.set_ForceStop(False)
            request.set_connect_timeout(10000)
            request.set_read_timeout(10000)
            client.do_action_with_exception(request)
            return "🛑 已发送关机指令"
        except Exception as e:
            return f"❌ 关机失败: {e}"

# ================== 6. 主循环流程 ==================
def main():
    logger.info("阿里云 ECS 监控程序已启动...")
    send_tg_message(f"🚀 <b>阿里云 ECS 监控程序已启动</b>\n将每 {CHECK_INTERVAL_SECONDS // 60} 分钟为您播报一次服务器状态。")

    while True:
        try:
            logger.info("开始执行本轮巡检...")
            traffic_gb = get_total_traffic_gb()
            ecs_status = get_ecs_status()
            action_msg = ""

            if traffic_gb is None or ecs_status in ["Error", "NotFound"]:
                action_msg = "⚠️ 获取数据失败，跳过本轮操作。"
            else:
                if traffic_gb < TRAFFIC_THRESHOLD_GB:
                    action_msg = control_ecs("start", ecs_status)
                else:
                    action_msg = control_ecs("stop", ecs_status)

            # 组装推送消息
            traffic_display = f"{traffic_gb:.2f} GB" if traffic_gb is not None else "未知"
            tg_msg = (
                f"🤖 <b>ECS 巡检播报</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>当前流量:</b> {traffic_display} / {TRAFFIC_THRESHOLD_GB} GB\n"
                f"💻 <b>实例状态:</b> {ecs_status}\n"
                f"⚙️ <b>执行动作:</b> {action_msg}"
            )

            logger.info(f"巡检完成。流量:{traffic_display}, 状态:{ecs_status}")
            send_tg_message(tg_msg)

        except Exception as e:
            logger.error(f"主循环发生未捕获异常: {e}")

        # 暂停进入下一轮
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
