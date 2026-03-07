from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
from astrbot.api.provider import LLMResponse, ProviderRequest
import platform
import psutil
import datetime
import os
import time
import re
import subprocess
import asyncio
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass

# ==================== 撤回防回复相关常量 ====================
NOTICE_GROUP_RECALL = "group_recall"
NOTICE_FRIEND_RECALL = "friend_recall"
RECORD_EXPIRE_SECONDS = 300  # 5分钟
CLEANUP_INTERVAL = 60

# ==================== 撤回防回复数据结构 ====================
@dataclass(slots=True)
class PendingRequest:
    """正在处理的 LLM 请求记录"""
    message_id: str
    unified_msg_origin: str
    sender_id: str
    timestamp: float
    event: Optional[AstrMessageEvent] = None

@dataclass(slots=True)
class RecalledMessage:
    """已撤回的消息记录"""
    message_id: str
    unified_msg_origin: str
    operator_id: str
    timestamp: float

@dataclass
class PluginStats:
    """插件统计信息（仅内部记录）"""
    recalls_detected: int = 0
    llm_requests_blocked: int = 0
    llm_responses_blocked: int = 0
    send_blocked: int = 0

# ==================== 撤回状态管理器 ====================
class RecallStateManager:
    """撤回状态管理器"""
    
    def __init__(self):
        self._pending_requests: Dict[str, PendingRequest] = {}
        self._recalled_messages: Dict[str, RecalledMessage] = {}
        self._lock = asyncio.Lock()
    
    @staticmethod
    def _compose_key(unified_msg_origin: str, message_id: str) -> str:
        return f"{unified_msg_origin}::{message_id}"
    
    async def add_pending_request(
        self, message_id: str, unified_msg_origin: str, sender_id: str,
        event: Optional[AstrMessageEvent] = None
    ) -> None:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            self._pending_requests[key] = PendingRequest(
                message_id=message_id,
                unified_msg_origin=unified_msg_origin,
                sender_id=sender_id,
                timestamp=time.time(),
                event=event
            )
    
    async def remove_pending_request(self, message_id: str, unified_msg_origin: str) -> Optional[PendingRequest]:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            return self._pending_requests.pop(key, None)
    
    async def get_pending_request(self, message_id: str, unified_msg_origin: str) -> Optional[PendingRequest]:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            return self._pending_requests.get(key)
    
    async def add_recalled_message(self, message_id: str, unified_msg_origin: str, operator_id: str) -> None:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            self._recalled_messages[key] = RecalledMessage(
                message_id=message_id,
                unified_msg_origin=unified_msg_origin,
                operator_id=operator_id,
                timestamp=time.time()
            )
    
    async def is_recalled(self, message_id: str, unified_msg_origin: str) -> bool:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            return key in self._recalled_messages
    
    async def get_recalled_message(self, message_id: str, unified_msg_origin: str) -> Optional[RecalledMessage]:
        key = self._compose_key(unified_msg_origin, message_id)
        async with self._lock:
            return self._recalled_messages.get(key)
    
    async def cleanup_expired(self, expire_seconds: float = RECORD_EXPIRE_SECONDS) -> int:
        now = time.time()
        cleaned = 0
        async with self._lock:
            expired_pending = [k for k, v in self._pending_requests.items() if now - v.timestamp > expire_seconds]
            for k in expired_pending:
                del self._pending_requests[k]
                cleaned += 1
            expired_recalled = [k for k, v in self._recalled_messages.items() if now - v.timestamp > expire_seconds]
            for k in expired_recalled:
                del self._recalled_messages[k]
                cleaned += 1
        return cleaned
    
    async def get_stats(self) -> Tuple[int, int]:
        async with self._lock:
            return len(self._pending_requests), len(self._recalled_messages)

# ==================== 主插件类 ====================
@register("astrbot_plugin_XYTUFunction", "Tangzixy , Slime , SLserver , XYTUworkshop", "Astrbot基础功能插件？ 一个就够了！", "v0.4.1", "https://github.com/XYTUworkshop/astrbot_plugin_XYTUFunction")
class XYTUFunctionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.awake_words = config.get("awake_words", ["XYTU", "XYTUFT"])
        logger.info(f"XYTUFunction 插件 v0.4.0 初始化，唤醒词: {self.awake_words}")
        
        # 撤回防回复相关
        self.recall_enabled = config.get("recall_prevention_enabled", False)
        if self.recall_enabled:
            self._state = RecallStateManager()
            self._stats = PluginStats()
            self._cleanup_task = None
            logger.info("[XYTUFunction] 撤回防回复功能已启用")
        else:
            logger.info("[XYTUFunction] 撤回防回复功能未启用")
        
    # ==================== 原有状态和赞我功能 ====================
    def _get_cpu_model(self) -> str:
        """获取CPU型号 - 使用多种方法确保准确性"""
        cpu_model = "未知"
        try:
            try:
                import cpuinfo
                cpu_info = cpuinfo.get_cpu_info()
                if cpu_info and 'brand_raw' in cpu_info:
                    cpu_model = cpu_info['brand_raw']
                    return cpu_model
            except ImportError:
                logger.warning("cpuinfo 库未安装，使用其他方法获取CPU型号")
                pass
            system_name = platform.system()
            if system_name == "Windows":
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                    cpu_model = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                    cpu_model = cpu_model.strip()
                    winreg.CloseKey(key)
                except:
                    try:
                        result = subprocess.run(
                            ["wmic", "cpu", "get", "name"],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                        if result.returncode == 0:
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                cpu_model = lines[1].strip()
                    except:
                        pass
            elif system_name == "Linux":
                try:
                    with open("/proc/cpuinfo", "r", encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if line.startswith("model name"):
                                cpu_model = line.split(":")[1].strip()
                                break
                except:
                    try:
                        result = subprocess.run(
                            ["lscpu"],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                if "Model name" in line or "型号名称" in line:
                                    cpu_model = line.split(":")[1].strip()
                                    break
                    except:
                        pass
            elif system_name == "Darwin":  
                try:
                    result = subprocess.run(
                        ["sysctl", "-n", "machdep.cpu.brand_string"],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    if result.returncode == 0:
                        cpu_model = result.stdout.strip()
                except:
                    pass
            if cpu_model == "未知" or "Family" in cpu_model or "Model" in cpu_model:
                cpu_model = platform.processor()
            cpu_model = ' '.join(cpu_model.split())
        except Exception as e:
            logger.error(f"获取CPU型号失败: {e}")
            cpu_model = "未知"
        return cpu_model
    
    def _get_cpu_info(self) -> tuple:
        try:
            cpu_model = self._get_cpu_model()
            cpu_percent = psutil.cpu_percent(interval=0.5)
            if "(" in cpu_model and ")" in cpu_model:
                cpu_model = re.sub(r'\([^)]*\)', '', cpu_model).strip()
            redundant_words = ["CPU", "Processor", "processor", "@", "(R)", "(TM)", "  "]
            for word in redundant_words:
                cpu_model = cpu_model.replace(word, "").strip()
            cpu_model = ' '.join(cpu_model.split())
            return cpu_model, f"{cpu_percent:.1f}%"
        except Exception as e:
            logger.error(f"获取CPU信息失败: {e}")
            return "未知", "0%"
    
    def _get_greeting(self) -> str:
        hour = datetime.datetime.now().hour
        if 0 <= hour < 6:
            return "凌晨"
        elif 6 <= hour < 12:
            return "早上"
        elif 12 <= hour < 14:
            return "中午"
        elif 14 <= hour < 18:
            return "下午"
        elif 18 <= hour < 21:
            return "晚上"
        else:
            return "深夜"
    
    def _get_memory_info(self) -> tuple:
        try:
            memory = psutil.virtual_memory()
            total_gb = memory.total / (1024 ** 3)
            used_gb = memory.used / (1024 ** 3)
            percent = memory.percent
            return f"{used_gb:.1f}G/{total_gb:.1f}G", f"{percent:.1f}%"
        except Exception as e:
            logger.error(f"获取内存信息失败: {e}")
            return "0G/0G", "0%"
    
    def _get_system_info(self) -> tuple:
        try:
            if platform.system() == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                    product_name = winreg.QueryValueEx(key, "ProductName")[0]
                    release_id = winreg.QueryValueEx(key, "ReleaseId")[0] if "ReleaseId" in [winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])] else ""
                    winreg.CloseKey(key)
                    if "(" in product_name and ")" in product_name:
                        product_name = re.sub(r'\s*\([^)]*\)', '', product_name)
                    system_info = f"Windows {product_name}"
                except:
                    system_info = f"{platform.system()} {platform.release()}"
                    system_info = re.sub(r'\s*\([^)]*\)', '', system_info)
            else:
                system_info = f"{platform.system()} {platform.release()}"
            boot_time = psutil.boot_time()
            now = time.time()
            uptime_seconds = now - boot_time
            uptime_days = int(uptime_seconds // (24 * 3600))
            uptime_hours = int((uptime_seconds % (24 * 3600)) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            if uptime_days > 0:
                uptime_str = f"{uptime_days}天{uptime_hours}小时{uptime_minutes}分"
            else:
                uptime_str = f"{uptime_hours}小时{uptime_minutes}分"
            return system_info, uptime_str
        except Exception as e:
            logger.error(f"获取系统信息失败: {e}")
            return platform.platform(), "未知"
    
    def _get_disk_info(self) -> List[str]:
        disk_info = []
        try:
            partitions = psutil.disk_partitions(all=False)
            for partition in partitions:
                try:
                    if 'cdrom' in partition.opts or partition.fstype == '':
                        continue
                    usage = psutil.disk_usage(partition.mountpoint)
                    total_gb = usage.total / (1024 ** 3)
                    used_gb = usage.used / (1024 ** 3)
                    percent = usage.percent
                    device = partition.device
                    if platform.system() == "Windows":
                        device = partition.device
                    elif platform.system() == "Linux":
                        device = os.path.basename(partition.device)
                    disk_info.append(f"   {device}: {used_gb:.1f}G/{total_gb:.1f}G | {percent:.1f}%")
                except Exception as e:
                    logger.warning(f"获取分区 {partition.mountpoint} 信息失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"获取硬盘信息失败: {e}")
            disk_info.append("   无法获取硬盘信息")
        return disk_info
    
    async def _send_like(self, event: AstrMessageEvent) -> bool:
        """给用户点赞"""
        try:
            platform_name = event.get_platform_name()
            if platform_name != "aiocqhttp":
                logger.warning(f"赞我功能不支持平台: {platform_name}")
                return False
            user_id = event.get_sender_id()
            if not user_id:
                logger.error("无法获取用户ID")
                return False
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            if not isinstance(event, AiocqhttpMessageEvent):
                logger.error("事件类型不是AiocqhttpMessageEvent")
                return False
            client = event.bot
            if not client:
                logger.error("无法获取QQ客户端")
                return False
            payloads = {"user_id": int(user_id), "times": 10}
            ret = await client.api.call_action('send_like', **payloads)
            if ret is None:
                logger.info(f"点赞API返回None，可能表示成功（用户ID: {user_id}）")
                return True
            if isinstance(ret, dict):
                if ret.get('status') == 'ok' or ret.get('retcode') == 0:
                    logger.info(f"成功给用户 {user_id} 点了10个赞")
                    return True
                else:
                    logger.error(f"点赞失败: {ret}")
                    event.stop_event()
                    return False
            else:
                logger.info(f"点赞API返回: {ret}，视为成功")
                return True
        except Exception as e:
            error_msg = str(e)
            logger.error(f"调用点赞API失败: {error_msg}")
            if "已达上限" in error_msg or "点赞失败" in error_msg:
                event.stop_event()
            return False
    
    def _get_raw_message(self, event: AstrMessageEvent) -> str:
        """获取原始消息"""
        try:
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'raw_message'):
                if isinstance(event.message_obj.raw_message, str):
                    return event.message_obj.raw_message
                elif hasattr(event.message_obj.raw_message, '__str__'):
                    raw_str = str(event.message_obj.raw_message)
                    if "'raw_message':" in raw_str:
                        try:
                            start = raw_str.find("'raw_message':") + len("'raw_message':")
                            end = raw_str.find(",", start)
                            if end == -1:
                                end = raw_str.find("}", start)
                            if end != -1:
                                raw_msg = raw_str[start:end].strip()
                                if raw_msg.startswith("'") and raw_msg.endswith("'"):
                                    raw_msg = raw_msg[1:-1]
                                elif raw_msg.startswith('"') and raw_msg.endswith('"'):
                                    raw_msg = raw_msg[1:-1]
                                return raw_msg
                        except:
                            pass
                    return raw_str
            if hasattr(event, 'raw_message'):
                return str(event.raw_message)
            return event.message_str
        except Exception as e:
            logger.error(f"获取原始消息失败: {e}")
            return ""
    
    def _check_awake_and_trigger(self, event: AstrMessageEvent, trigger_words: List[str]) -> bool:
        """检查是否被唤醒并且消息匹配触发词"""
        try:
            raw_msg = self._get_raw_message(event)
            if not raw_msg:
                raw_msg = event.message_str
            logger.info(f"原始消息内容: '{raw_msg}'，唤醒词列表: {self.awake_words}")
            for awake_word in self.awake_words:
                if raw_msg.startswith(awake_word):
                    remaining = raw_msg[len(awake_word):].strip()
                    for word in trigger_words:
                        if remaining.lower() == word.lower():
                            logger.info(f"匹配成功: 唤醒词='{awake_word}', 触发词='{word}'")
                            return True
            return False
        except Exception as e:
            logger.error(f"检查唤醒和触发失败: {e}")
            return False
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_status(self, event: AstrMessageEvent):
        """处理状态请求"""
        try:
            config = self.config
            if not config.get("status_enabled", False):
                return
            trigger_words = config.get("status_trigger_words", ["状态", "status"])
            if not trigger_words:
                trigger_words = ["状态", "status"]
            if not self._check_awake_and_trigger(event, trigger_words):
                return
            username = event.get_sender_name()
            greeting = self._get_greeting()
            cpu_model, cpu_percent = self._get_cpu_info()
            memory_str, memory_percent = self._get_memory_info()
            system_version, uptime = self._get_system_info()
            disk_info = self._get_disk_info()
            response = f"{greeting}好呀{username} 随时待命\n"
            response += "当前状态：\n"
            response += " CPU\n"
            response += f"   {cpu_model} | {cpu_percent}\n"
            response += " RAM\n"
            response += f"   {memory_str} | {memory_percent}\n"
            response += " System\n"
            response += f"   {system_version} | {uptime}\n"
            if disk_info:
                response += " Disk\n"
                response += "\n".join(disk_info)
            yield event.plain_result(response)
        except Exception as e:
            logger.error(f"处理状态请求失败: {e}")
            try:
                yield event.plain_result("获取状态信息时出现错误，请检查插件配置和依赖。")
            except:
                pass
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_like(self, event: AstrMessageEvent):
        """处理点赞请求"""
        try:
            config = self.config
            if not config.get("like_enabled", False):
                return
            trigger_words = config.get("like_trigger_words", ["赞我", "zanwo"])
            if not trigger_words:
                trigger_words = ["赞我", "zanwo"]
            if not self._check_awake_and_trigger(event, trigger_words):
                return
            username = event.get_sender_name()
            success = await self._send_like(event)
            if success:
                response = f"给你点了10个赞 记得回我哦{username}"
            else:
                response = f"呀 怎么失败了{username} 明天再来罢"
            yield event.plain_result(response)
        except Exception as e:
            logger.error(f"处理点赞请求失败: {e}")
            try:
                username = event.get_sender_name()
                yield event.plain_result(f"点赞过程中出现错误{username}")
            except:
                pass
    
    # ==================== 撤回防回复功能 ====================
    def _get_message_id(self, event: AstrMessageEvent) -> Optional[str]:
        """从事件中提取原始消息 ID"""
        try:
            raw = getattr(event.message_obj, 'raw_message', None)
            if raw:
                if isinstance(raw, dict):
                    msg_id = raw.get('message_id')
                    if msg_id:
                        return str(msg_id)
                elif hasattr(raw, 'message_id'):
                    msg_id = getattr(raw, 'message_id', None)
                    if msg_id:
                        return str(msg_id)
            msg_id = getattr(event.message_obj, 'message_id', None)
            if msg_id:
                msg_id_str = str(msg_id)
                compact = msg_id_str.replace("-", "")
                if len(compact) == 32 and compact.isalnum():
                    return None
                return msg_id_str
        except Exception as e:
            logger.debug(f"[XYTUFunction] 提取消息ID失败: {e}")
        return None
    
    def _is_recall_event(self, event: AstrMessageEvent) -> Tuple[bool, Optional[str], Optional[str]]:
        """检查是否为撤回事件"""
        try:
            raw = getattr(event.message_obj, 'raw_message', None)
            if not raw:
                return False, None, None
            notice_type = None
            if isinstance(raw, dict):
                notice_type = raw.get('notice_type')
            elif hasattr(raw, 'notice_type'):
                notice_type = getattr(raw, 'notice_type', None)
            if notice_type not in (NOTICE_GROUP_RECALL, NOTICE_FRIEND_RECALL):
                return False, None, None
            if isinstance(raw, dict):
                recalled_msg_id = raw.get('message_id')
                operator_id = raw.get('operator_id') or raw.get('user_id')
            else:
                recalled_msg_id = getattr(raw, 'message_id', None)
                operator_id = getattr(raw, 'operator_id', None) or getattr(raw, 'user_id', None)
            if recalled_msg_id:
                return True, str(recalled_msg_id), str(operator_id) if operator_id else None
        except Exception as e:
            logger.debug(f"[XYTUFunction] 检查撤回事件失败: {e}")
        return False, None, None
    
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def on_all_message(self, event: AstrMessageEvent) -> None:
        """监听所有消息，检测撤回事件"""
        if not self.recall_enabled:
            return
        is_recall, recalled_msg_id, operator_id = self._is_recall_event(event)
        if not is_recall or not recalled_msg_id:
            return
        self._stats.recalls_detected += 1
        umo = event.unified_msg_origin
        logger.info(f"[XYTUFunction] 检测到撤回事件 | 消息ID: {recalled_msg_id} | 操作者: {operator_id} | 会话: {umo}")
        await self._state.add_recalled_message(recalled_msg_id, umo, operator_id or "")
        pending = await self._state.get_pending_request(recalled_msg_id, umo)
        if pending and pending.event:
            logger.info(f"[XYTUFunction] 找到待处理的 LLM 请求，正在取消 | 消息ID: {recalled_msg_id}")
            pending.event.stop_event()
            self._stats.llm_requests_blocked += 1
        event.stop_event()
    
    @filter.on_llm_request(priority=100)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self.recall_enabled:
            return
        msg_id = self._get_message_id(event)
        if not msg_id:
            return
        umo = event.unified_msg_origin
        sender_id = event.get_sender_id()
        await self._state.add_pending_request(msg_id, umo, sender_id, event)
        if await self._state.is_recalled(msg_id, umo):
            logger.info(f"[XYTUFunction] LLM 请求阶段拦截 | 消息已被撤回，阻止请求 | 消息ID: {msg_id}")
            event.stop_event()
            self._stats.llm_requests_blocked += 1
    
    @filter.on_llm_response(priority=100)
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
        if not self.recall_enabled:
            return
        msg_id = self._get_message_id(event)
        if not msg_id:
            return
        umo = event.unified_msg_origin
        if await self._state.is_recalled(msg_id, umo):
            logger.info(f"[XYTUFunction] LLM 响应阶段拦截 | 消息已被撤回，阻止响应 | 消息ID: {msg_id}")
            event.stop_event()
            self._stats.llm_responses_blocked += 1
    
    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent) -> None:
        if not self.recall_enabled:
            return
        msg_id = self._get_message_id(event)
        if not msg_id:
            return
        umo = event.unified_msg_origin
        await asyncio.sleep(0.1)
        if await self._state.is_recalled(msg_id, umo):
            logger.info(f"[XYTUFunction] 发送阶段拦截 | 消息已被撤回，阻止发送 | 消息ID: {msg_id}")
            event.stop_event()
            self._stats.send_blocked += 1
    
    @filter.after_message_sent(priority=100)
    async def after_message_sent(self, event: AstrMessageEvent) -> None:
        if not self.recall_enabled:
            return
        msg_id = self._get_message_id(event)
        if not msg_id:
            return
        await self._state.remove_pending_request(msg_id, event.unified_msg_origin)
        logger.debug(f"[XYTUFunction] 消息已发送，清理记录 | 消息ID: {msg_id}")
    
    @filter.on_astrbot_loaded()
    async def on_loaded(self, *args, **kwargs) -> None:
        if not self.recall_enabled:
            return
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.debug("[XYTUFunction] 后台清理任务已启动")
    
    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                cleaned = await self._state.cleanup_expired()
                if cleaned > 0:
                    pending, recalled = await self._state.get_stats()
                    logger.debug(f"[XYTUFunction] 已清理 {cleaned} 条过期记录 | 当前: 待处理 {pending}, 已撤回 {recalled}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[XYTUFunction] 清理任务出错: {e}")
    
    async def terminate(self):
        """插件卸载时清理"""
        if hasattr(self, '_cleanup_task') and self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("XYTUFunction 插件卸载")
