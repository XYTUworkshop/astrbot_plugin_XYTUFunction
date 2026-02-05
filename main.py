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
from typing import List, Tuple

# 配置常量
CONFIG_STATUS_ENABLED = "status_enabled"
CONFIG_TRIGGER_WORDS = "status_trigger_words"

# 子进程调用超时时间（秒）
SUBPROCESS_TIMEOUT = 3

# 默认配置
DEFAULT_TRIGGER_WORDS = ["状态", "status"]


@register("astrbot_plugin_XYTUFunction", "Tangzixy , Slime , SLserver , XYTUworkshop", "Astrbot基础功能插件？ 一个就够了！", "v0.1.0", "https://github.com/XYTUworkshop/astrbot_plugin_XYTUFunction")
class XYTUFunctionPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._cpu_usage_cache = 0.0
        self._last_cpu_check = 0
        logger.info("XYTUFunction 插件初始化")
    
    @staticmethod
    def _clean_string(text: str) -> str:
        """清理字符串：移除括号内容和冗余词"""
        if not text:
            return text
        
        # 移除括号及其内容
        if "(" in text and ")" in text:
            text = re.sub(r'\s*\([^)]*\)', '', text)
        
        # 移除冗余词
        redundant_words = ["CPU", "Processor", "processor", "@", "(R)", "(TM)", "®", "™", "  "]
        for word in redundant_words:
            text = text.replace(word, "")
        
        # 清理多余空格
        text = ' '.join(text.split())
        
        return text.strip()
    
    def _get_cpu_model(self) -> str:
        """获取CPU型号"""
        cpu_model = "未知"
        
        try:
            # 方法1: 使用 cpuinfo 库 (最准确)
            try:
                import cpuinfo
                cpu_info = cpuinfo.get_cpu_info()
                if cpu_info and 'brand_raw' in cpu_info:
                    cpu_model = cpu_info['brand_raw']
                    return self._clean_string(cpu_model)
            except ImportError:
                logger.warning("cpuinfo 库未安装，使用其他方法获取CPU型号")
                pass
                
            # 方法2: 根据操作系统使用系统命令
            system_name = platform.system()
            
            if system_name == "Windows":
                # Windows系统 - 注册表方式
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
                    cpu_model = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                    winreg.CloseKey(key)
                except (OSError, WindowsError):
                    # 备用方法: 使用 wmic 命令
                    try:
                        result = subprocess.run(
                            ["wmic", "cpu", "get", "name"],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore',
                            timeout=SUBPROCESS_TIMEOUT
                        )
                        if result.returncode == 0:
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                cpu_model = lines[1].strip()
                    except (subprocess.SubprocessError, FileNotFoundError):
                        pass
            
            elif system_name == "Linux":
                # Linux系统
                try:
                    with open("/proc/cpuinfo", "r", encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if line.startswith("model name"):
                                cpu_model = line.split(":", 1)[1].strip()
                                break
                except (OSError, FileNotFoundError):
                    # 备用方法: 使用 lscpu 命令
                    try:
                        result = subprocess.run(
                            ["lscpu"],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore',
                            timeout=SUBPROCESS_TIMEOUT
                        )
                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                if "Model name" in line or "型号名称" in line:
                                    cpu_model = line.split(":", 1)[1].strip()
                                    break
                    except (subprocess.SubprocessError, FileNotFoundError):
                        pass
            
            elif system_name == "Darwin":  # macOS
                try:
                    result = subprocess.run(
                        ["sysctl", "-n", "machdep.cpu.brand_string"],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        timeout=SUBPROCESS_TIMEOUT
                    )
                    if result.returncode == 0:
                        cpu_model = result.stdout.strip()
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass
            
            # 如果以上方法都失败，使用 platform 库的备用方法
            if cpu_model == "未知" or "Family" in cpu_model or "Model" in cpu_model:
                cpu_model = platform.processor() or "未知"
            
            return self._clean_string(cpu_model)
            
        except Exception as e:
            logger.error(f"获取CPU型号失败: {e}")
            return "未知"
    
    def _get_cpu_info(self) -> Tuple[str, str]:
        """获取CPU信息"""
        try:
            # 获取CPU型号
            cpu_model = self._get_cpu_model()
            
            # 获取CPU占用率 - 使用缓存减少延迟
            current_time = time.time()
            if current_time - self._last_cpu_check >= 1.0:  # 至少1秒缓存
                # 使用非阻塞方式获取CPU使用率
                self._cpu_usage_cache = psutil.cpu_percent(interval=None)
                self._last_cpu_check = current_time
            
            cpu_percent = self._cpu_usage_cache
            
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
    
    def _get_memory_info(self) -> Tuple[str, str]:
        """获取内存信息"""
        try:
            memory = psutil.virtual_memory()
            # 转换为GB
            total_gb = memory.total / (1024 ** 3)
            used_gb = memory.used / (1024 ** 3)
            percent = memory.percent
            
            return f"{used_gb:.1f}G/{total_gb:.1f}G", f"{percent:.1f}%"
        except Exception as e:
            logger.error(f"获取内存信息失败: {e}")
            return "0G/0G", "0%"
    
    def _get_system_info(self) -> Tuple[str, str]:
        """获取系统信息"""
        try:
            # 系统版本
            if platform.system() == "Windows":
                import winreg
                try:
                    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
                    try:
                        product_name = winreg.QueryValueEx(key, "ProductName")[0]
                        # 简化 ReleaseId 检查逻辑
                        try:
                            release_id = winreg.QueryValueEx(key, "ReleaseId")[0]
                        except FileNotFoundError:
                            release_id = ""
                    finally:
                        winreg.CloseKey(key)
                    
                    # 清理产品名称
                    product_name = self._clean_string(product_name)
                    
                    # 移除重复的"Windows"前缀
                    if product_name.startswith("Windows"):
                        product_name = product_name[7:].strip()
                    
                    system_info = f"Windows {product_name}"
                except (OSError, WindowsError):
                    system_info = f"{platform.system()} {platform.release()}"
                    system_info = self._clean_string(system_info)
            else:
                system_info = f"{platform.system()} {platform.release()}"
            
            # 开机时间
            boot_time = psutil.boot_time()
            now = time.time()
            uptime_seconds = now - boot_time
            
            # 转换为易读格式
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
                    # 跳过CD-ROM等只读设备
                    if 'cdrom' in partition.opts or partition.fstype == '':
                        continue
                    
                    usage = psutil.disk_usage(partition.mountpoint)
                    total_gb = usage.total / (1024 ** 3)
                    used_gb = usage.used / (1024 ** 3)
                    percent = usage.percent
                    
                    # 获取设备名称
                    device = partition.device
                    
                    # 如果是Windows，只显示盘符
                    if platform.system() == "Windows":
                        device = partition.device.rstrip('\\')
                    elif platform.system() == "Linux":
                        # Linux下显示设备和挂载点
                        device_name = os.path.basename(partition.device)
                        mount_point = partition.mountpoint
                        device = f"{device_name} ({mount_point})"
                    
                    disk_info.append(f"   {device}: {used_gb:.1f}G/{total_gb:.1f}G | {percent:.1f}%")
                except (OSError, PermissionError) as e:
                    logger.warning(f"获取分区 {partition.mountpoint} 信息失败: {e}")
                    continue
        except Exception as e:
            logger.error(f"获取硬盘信息失败: {e}")
            disk_info.append("   无法获取硬盘信息")
        
        return disk_info
    
    def _check_trigger_word(self, message: str, trigger_words: List[str]) -> bool:
        """检查消息是否包含触发词（单词边界匹配）"""
        if not message or not trigger_words:
            return False
        
        message_lower = message.strip().lower()
        
        # 构建正则表达式，使用单词边界匹配
        pattern_parts = []
        for word in trigger_words:
            word_clean = word.strip().lower()
            if word_clean:
                pattern_parts.append(re.escape(word_clean))
        
        if not pattern_parts:
            return False
        
        # 构建正则表达式：\b(word1|word2|...)\b
        pattern = r'\b(' + '|'.join(pattern_parts) + r')\b'
        
        try:
            return bool(re.search(pattern, message_lower))
        except re.error:
            # 正则表达式出错时回退到简单匹配
            return any(word.strip().lower() in message_lower for word in trigger_words)
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息"""
        try:
            # 获取配置
            config = self.config
            
            # 检查功能是否启用
            if not config.get(CONFIG_STATUS_ENABLED, False):
                return
            
            # 获取触发词列表
            trigger_words = config.get(CONFIG_TRIGGER_WORDS, DEFAULT_TRIGGER_WORDS)
            if not trigger_words:
                trigger_words = DEFAULT_TRIGGER_WORDS
            
            # 检查消息是否匹配触发词
            message_str = event.message_str
            if not self._check_trigger_word(message_str, trigger_words):
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
            response = f"{greeting}好呀 {username}  随时待命\n"
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
    
    async def terminate(self):
        """插件卸载时调用"""
        logger.info("XYTUFunction 插件卸载")
