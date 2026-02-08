from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import platform
import psutil
import datetime
import os
import time
import re
import subprocess
from typing import List

@register("astrbot_plugin_XYTUFunction", "Tangzixy , Slime , SLserver , XYTUworkshop", "Astrbot基础功能插件？ 一个就够了！", "v0.3.2", "https://github.com/XYTUworkshop/astrbot_plugin_XYTUFunction")
class XYTUFunctionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 获取配置中的唤醒词列表，默认为["XYTU", "XYTUFT"]
        self.awake_words = config.get("awake_words", ["XYTU", "XYTUFT"])
        logger.info(f"XYTUFunction 插件初始化，唤醒词: {self.awake_words}")
        
    # ========================================== 状态 ==========================================
    
    def _get_cpu_model(self) -> str:
        """获取CPU型号 - 使用多种方法确保准确性"""
        cpu_model = "未知"
        
        try:
            # cpuinfo 库
            try:
                import cpuinfo
                cpu_info = cpuinfo.get_cpu_info()
                if cpu_info and 'brand_raw' in cpu_info:
                    cpu_model = cpu_info['brand_raw']
                    return cpu_model
            except ImportError:
                logger.warning("cpuinfo 库未安装，使用其他方法获取CPU型号")
                pass
                
            # 系统命令 备用 1
            system_name = platform.system()
            
            if system_name == "Windows":
                # Windows
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                    cpu_model = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                    cpu_model = cpu_model.strip()
                    winreg.CloseKey(key)
                except:
                    #  wmic 命令 备用 2
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
                # Linux
                try:
                    with open("/proc/cpuinfo", "r", encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if line.startswith("model name"):
                                cpu_model = line.split(":")[1].strip()
                                break
                except:
                    # lscpu 命令 备用 1
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
                # macOS
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
            
            # platform 最终备用
            if cpu_model == "未知" or "Family" in cpu_model or "Model" in cpu_model:
                cpu_model = platform.processor()
                
            # 移除多余空格
            cpu_model = ' '.join(cpu_model.split())
            
        except Exception as e:
            logger.error(f"获取CPU型号失败: {e}")
            cpu_model = "未知"
        
        return cpu_model
    
    def _get_cpu_info(self) -> tuple:
        """获取CPU信息"""
        try:
            # CPU型号
            cpu_model = self._get_cpu_model()
            
            # CPU占用率
            cpu_percent = psutil.cpu_percent(interval=0.5)
            
            # 移除冗余信息
            if "(" in cpu_model and ")" in cpu_model:
                cpu_model = re.sub(r'\([^)]*\)', '', cpu_model).strip()
            
            # 移除常见冗余词
            redundant_words = ["CPU", "Processor", "processor", "@", "(R)", "(TM)", "  "]
            for word in redundant_words:
                cpu_model = cpu_model.replace(word, "").strip()
            
            # 移除多余的空格
            cpu_model = ' '.join(cpu_model.split())
            
            return cpu_model, f"{cpu_percent:.1f}%"
        except Exception as e:
            logger.error(f"获取CPU信息失败: {e}")
            return "未知", "0%"
    
    def _get_greeting(self) -> str:
        """获取问候语"""
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
        """获取内存信息"""
        try:
            memory = psutil.virtual_memory()
            # 转为GB
            total_gb = memory.total / (1024 ** 3)
            used_gb = memory.used / (1024 ** 3)
            percent = memory.percent
            
            return f"{used_gb:.1f}G/{total_gb:.1f}G", f"{percent:.1f}%"
        except Exception as e:
            logger.error(f"获取内存信息失败: {e}")
            return "0G/0G", "0%"
    
    def _get_system_info(self) -> tuple:
        """获取系统信息"""
        try:
            # 系统版本
            if platform.system() == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                    product_name = winreg.QueryValueEx(key, "ProductName")[0]
                    release_id = winreg.QueryValueEx(key, "ReleaseId")[0] if "ReleaseId" in [winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])] else ""
                    winreg.CloseKey(key)
                    
                    # 移除括号内容
                    if "(" in product_name and ")" in product_name:
                        product_name = re.sub(r'\s*\([^)]*\)', '', product_name)
                    
                    system_info = f"Windows {product_name}"
                    # 移除release_id
                except:
                    system_info = f"{platform.system()} {platform.release()}"
                    # 处理可能存在的括号
                    system_info = re.sub(r'\s*\([^)]*\)', '', system_info)
            else:
                system_info = f"{platform.system()} {platform.release()}"
            
            # 开机时间
            boot_time = psutil.boot_time()
            now = time.time()
            uptime_seconds = now - boot_time
            
            # 转换格式
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
        """获取硬盘信息"""
        disk_info = []
        try:
            partitions = psutil.disk_partitions(all=False)
            for partition in partitions:
                try:
                    # 跳过只读设备
                    if 'cdrom' in partition.opts or partition.fstype == '':
                        continue
                    
                    usage = psutil.disk_usage(partition.mountpoint)
                    total_gb = usage.total / (1024 ** 3)
                    used_gb = usage.used / (1024 ** 3)
                    percent = usage.percent
                    
                    # 设备名称
                    device = partition.device
                    # Windows显示盘符
                    if platform.system() == "Windows":
                        device = partition.device
                    elif platform.system() == "Linux":
                        # Linux显示设备名 不显示挂载点
                        device = os.path.basename(partition.device)
                    
                    disk_info.append(f"   {device}: {used_gb:.1f}G/{total_gb:.1f}G | {percent:.1f}%")
                except Exception as e:
                    logger.warning(f"获取分区 {partition.mountpoint} 信息失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"获取硬盘信息失败: {e}")
            disk_info.append("   无法获取硬盘信息")
        
        return disk_info
    
    # ========================================== 赞我 ==========================================
    
    async def _send_like(self, event: AstrMessageEvent) -> bool:
        """
        给用户点赞
        返回: True表示成功，False表示失败
        """
        try:
            # 获取平台类型
            platform_name = event.get_platform_name()
            
            # 只支持QQ平台
            if platform_name != "aiocqhttp":
                logger.warning(f"赞我功能不支持平台: {platform_name}")
                return False
            
            # 用户ID
            user_id = event.get_sender_id()
            if not user_id:
                logger.error("无法获取用户ID")
                return False
            
            # 导入QQ消息事件类型
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            
            # 检查事件类型
            if not isinstance(event, AiocqhttpMessageEvent):
                logger.error("事件类型不是AiocqhttpMessageEvent")
                return False
            
            # 获取客户端
            client = event.bot
            if not client:
                logger.error("无法获取QQ客户端")
                return False
            
            # 调用点赞API
            payloads = {
                "user_id": int(user_id),
                "times": 10  # 点10个赞
            }
            
            # 调用API
            ret = await client.api.call_action('send_like', **payloads)
            
            # 检查返回结果
            if ret is None:
                logger.info(f"点赞API返回None，可能表示成功（用户ID: {user_id}）")
                return True
            
            # 检查返回状态
            if isinstance(ret, dict):
                if ret.get('status') == 'ok' or ret.get('retcode') == 0:
                    logger.info(f"成功给用户 {user_id} 点了10个赞")
                    return True
                else:
                    logger.error(f"点赞失败: {ret}")
                    # 停止事件传播 防止发送默认错误
                    event.stop_event()
                    return False
            else:
                # 有些协议端可能返回True
                logger.info(f"点赞API返回: {ret}，视为成功")
                return True
                
        except Exception as e:
            # 捕获所有异常
            error_msg = str(e)
            logger.error(f"调用点赞API失败: {error_msg}")
            
            # 根据错误信息判断是否达到上限
            if "已达上限" in error_msg or "点赞失败" in error_msg:
                # 停止事件传播，防止AstrBot Core发送默认错误回复
                event.stop_event()
            
            return False
    
    def _get_raw_message(self, event: AstrMessageEvent) -> str:
        """获取原始消息"""
        try:
            # 方法1: 从 message_obj.raw_message 获取
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'raw_message'):
                if isinstance(event.message_obj.raw_message, str):
                    return event.message_obj.raw_message
                elif hasattr(event.message_obj.raw_message, '__str__'):
                    # 尝试转换为字符串
                    raw_str = str(event.message_obj.raw_message)
                    # 如果 raw_str 看起来像是一个对象表示，尝试从中提取消息内容
                    # 从日志看，raw_message 是一个类似 <Event, {...}> 的字符串
                    # 我们需要从中提取 'raw_message' 字段
                    if "'raw_message':" in raw_str:
                        # 尝试提取 raw_message 字段的值
                        try:
                            # 找到 'raw_message': 的位置
                            start = raw_str.find("'raw_message':") + len("'raw_message':")
                            # 找到下一个逗号或右大括号
                            end = raw_str.find(",", start)
                            if end == -1:
                                end = raw_str.find("}", start)
                            if end != -1:
                                raw_msg = raw_str[start:end].strip()
                                # 去除可能的引号
                                if raw_msg.startswith("'") and raw_msg.endswith("'"):
                                    raw_msg = raw_msg[1:-1]
                                elif raw_msg.startswith('"') and raw_msg.endswith('"'):
                                    raw_msg = raw_msg[1:-1]
                                return raw_msg
                        except:
                            pass
                    return raw_str
            
            # 方法2: 直接尝试获取原始消息
            if hasattr(event, 'raw_message'):
                return str(event.raw_message)
            
            # 方法3: 回退到 message_str
            return event.message_str
            
        except Exception as e:
            logger.error(f"获取原始消息失败: {e}")
            return ""
    
    def _check_awake_and_trigger(self, event: AstrMessageEvent, trigger_words: List[str]) -> bool:
        """
        检查是否被唤醒并且消息匹配触发词
        
        规则:
        1. 原始消息以配置中的任一唤醒词开头
        2. 唤醒词之后的部分严格匹配触发词
        """
        try:
            # 获取原始消息
            raw_msg = self._get_raw_message(event)
            
            # 如果没有获取到原始消息，则回退到 message_str
            if not raw_msg:
                raw_msg = event.message_str
            
            # 记录调试信息
            logger.info(f"原始消息内容: '{raw_msg}'，唤醒词列表: {self.awake_words}")
            
            # 检查原始消息是否以配置中的任一唤醒词开头
            for awake_word in self.awake_words:
                if raw_msg.startswith(awake_word):
                    # 移除唤醒词和可能跟随的空格
                    remaining = raw_msg[len(awake_word):].strip()
                    
                    # 检查剩余部分是否严格匹配触发词
                    for word in trigger_words:
                        if remaining.lower() == word.lower():
                            logger.info(f"匹配成功: 唤醒词='{awake_word}', 触发词='{word}'")
                            return True
            
            return False
            
        except Exception as e:
            logger.error(f"检查唤醒和触发失败: {e}")
            return False
    
    # ============== 消息处理函数 ==============
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_status(self, event: AstrMessageEvent):
        """处理状态请求"""
        try:
            # 获取配置
            config = self.config
            
            # 检查功能是否启用
            if not config.get("status_enabled", False):
                return
            
            # 获取触发词列表
            trigger_words = config.get("status_trigger_words", ["状态", "status"])
            if not trigger_words:
                trigger_words = ["状态", "status"]
            
            # 检查是否应该触发（必须被唤醒且匹配触发词）
            if not self._check_awake_and_trigger(event, trigger_words):
                return
            
            # 获取发送者用户名
            username = event.get_sender_name()
            
            # 获取问候语
            greeting = self._get_greeting()
            
            # 获取系统信息
            cpu_model, cpu_percent = self._get_cpu_info()
            memory_str, memory_percent = self._get_memory_info()
            system_version, uptime = self._get_system_info()
            disk_info = self._get_disk_info()
            
            # 构建回复消息
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
            
            # 发送回复
            yield event.plain_result(response)
            
        except Exception as e:
            logger.error(f"处理状态请求失败: {e}")
            # 发送简单的错误提示
            try:
                yield event.plain_result("获取状态信息时出现错误，请检查插件配置和依赖。")
            except:
                pass
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_like(self, event: AstrMessageEvent):
        """处理点赞请求"""
        try:
            # 获取配置
            config = self.config
            
            # 检查功能是否启用
            if not config.get("like_enabled", False):
                return
            
            # 获取触发词列表
            trigger_words = config.get("like_trigger_words", ["赞我", "zanwo"])
            if not trigger_words:
                trigger_words = ["赞我", "zanwo"]
            
            # 检查是否应该触发（必须被唤醒且匹配触发词）
            if not self._check_awake_and_trigger(event, trigger_words):
                return
            
            # 获取发送者用户名
            username = event.get_sender_name()
            
            # 尝试点赞
            success = await self._send_like(event)
            
            # 根据结果发送回复
            if success:
                response = f"给你点了10个赞 记得回我哦{username}"
            else:
                response = f"呀 怎么失败了{username} 明天再来罢"
            
            # 发送回复
            yield event.plain_result(response)
            
        except Exception as e:
            logger.error(f"处理点赞请求失败: {e}")
            # 发送简单的错误提示
            try:
                username = event.get_sender_name()
                yield event.plain_result(f"点赞过程中出现错误{username}")
            except:
                pass
    
    async def terminate(self):
        """插件卸载时调用"""
        logger.info("XYTUFunction 插件卸载")
