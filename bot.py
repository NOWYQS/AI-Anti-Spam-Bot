"""
AI 反垃圾广告机器人 (AI Anti-Spam Bot)
官方项目：https://github.com/luoyanglang/AI-Anti-Spam-Bot
开发者：狼哥 (@luoyanglang)

功能：
1. 广告按钮管理 (/add_ad, /all_ad, /del_ad)
2. verification_times 验证机制
3. 灵活的检测策略配置
4. 配置验证和错误处理优化

如果本项目对您有帮助，请保留开发者信息，这是对开源作者最基本的尊重 🙏
"""
import base64
import logging
import sys
import os
from datetime import datetime
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ChatMemberHandler, ContextTypes, filters, CallbackQueryHandler
)
from config import config
from database import db, UserInfo, Advertisement
from ai import create_ai_client
from ai.prompts import USER_INFO_TEMPLATE
from developer_info import get_start_message

# 确保日志目录存在
os.makedirs('data', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 运行时统计（简单的内存统计）
class Stats:
    def __init__(self):
        self.checks_total = 0
        self.checks_passed = 0
        self.checks_banned = 0
        self.checks_failed = 0
        self.start_time = datetime.now()
    
    def record_check(self, result: str):
        self.checks_total += 1
        if result == 'passed':
            self.checks_passed += 1
        elif result == 'banned':
            self.checks_banned += 1
        elif result == 'failed':
            self.checks_failed += 1
    
    def get_stats(self) -> dict:
        uptime = datetime.now() - self.start_time
        return {
            'uptime_seconds': int(uptime.total_seconds()),
            'checks_total': self.checks_total,
            'checks_passed': self.checks_passed,
            'checks_banned': self.checks_banned,
            'checks_failed': self.checks_failed
        }

stats = Stats()

# 项目信息（请勿移除，这是对开源作者的尊重）
PROJECT_INFO = {
    'name': 'AI Anti-Spam Bot',
    'repo': 'https://github.com/luoyanglang/AI-Anti-Spam-Bot',
    'channel': 'https://t.me/langgefabu',
    'group': 'https://t.me/langgepython',
    'developer': '@luoyanglang',
    'demo_bot': '@xiaolangzaibot'
}

ai_client = create_ai_client()

# ============ 工具函数 ============

def is_owner(user_id: int) -> bool:
    """检查是否为超级管理员（可管理广告）"""
    owners = config.get("telegram.owners", [])
    return str(user_id) in owners

async def is_chat_admin(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """检查是否为群管理员"""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except:
        return False

def need_check(user: UserInfo) -> bool:
    """
    判断用户是否需要检测
    支持灵活的检测策略配置
    """
    # 检查验证次数限制
    max_verification = config.get("strategy.verification_times", 0)
    if max_verification > 0 and user.verification_times >= max_verification:
        return False
    
    # 检查加入天数
    max_days = config.get("strategy.joined_days", 3)
    joined_days = (datetime.now() - user.join_time).days
    if joined_days > max_days:
        return False
    
    # 检查发言次数（可选）
    check_message_count = config.get("strategy.check_message_count", True)
    if check_message_count:
        min_msgs = config.get("strategy.min_messages", 3)
        if user.message_count > min_msgs:
            return False
    
    return True

def build_user_info(user, db_user: UserInfo) -> str:
    """构建用户信息字符串（不包含用户名称，避免因名称误判）"""
    return USER_INFO_TEMPLATE.format(
        msg_count=db_user.message_count + 1,
        join_time=db_user.join_time.strftime("%Y-%m-%d %H:%M")
    )

def process_nickname(nickname: str) -> str:
    """
    处理用户名，用 spoiler 隐藏中间部分
    和 Go 版本一致：使用 || 包裹中间部分
    """
    if not nickname or not nickname.strip():
        return "未知用户"
    
    nickname = nickname.strip()
    # 先转义 MarkdownV2 特殊字符（spoiler 的 || 除外）
    escaped = escape_markdown_v2(nickname)
    
    length = len(escaped)
    if length == 1:
        return f"||{escaped}||"
    elif length == 2:
        return f"{escaped[0]}||{escaped[1]}||"
    else:
        # 保留首尾，中间用 spoiler 隐藏
        return f"{escaped[0]}||{escaped[1:-1]}||{escaped[-1]}"

def escape_markdown_v2(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def create_ban_keyboard() -> InlineKeyboardMarkup:
    """
    创建封禁通知的按钮
    包含：解封按钮 + 广告按钮
    """
    buttons = []
    
    # 第一行：解封按钮（占位，实际在 send_ban_notice 中动态生成）
    # buttons.append([InlineKeyboardButton("🔓 解除禁言", callback_data=f"unban_{user_id}")])
    
    # 后续行：广告按钮
    ads = db.get_valid_advertisements()
    for ad in ads:
        buttons.append([InlineKeyboardButton(ad.title, url=ad.url)])
    
    return InlineKeyboardMarkup(buttons) if buttons else None

async def send_ban_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, result):
    """发送禁言通知（带广告按钮 + 官方频道）"""
    name = f"{user.last_name or ''}{user.first_name or ''}"
    masked_name = process_nickname(name)
    user_link = f"tg://user?id={user.id}"
    
    # 转义特殊字符
    reason_escaped = escape_markdown_v2(result.reason or "无")
    mock_escaped = escape_markdown_v2(result.mock_text or "无")
    
    # 新格式
    notice = (
        f"\\#封禁预警\n"
        f"[{masked_name}]({user_link}) 请注意，你的用户名或发言存在违规\n"
        f"⚠️已被AI判断为高风险用户，永久封禁\n"
        f"风险分数：{result.score}\n"
        f"📋 违规原因：\n```\n{reason_escaped}\n```\n"
        f"🤖 AI 嘲讽：\n```\n{mock_escaped}\n```"
    )
    
    # 创建按钮：解封 + 官方频道 + 广告
    buttons = []
    buttons.append([InlineKeyboardButton("👮🏻 解封", callback_data=f"unban_{user.id}")])
    
    # 添加官方频道按钮（品牌曝光）
    buttons.append([
        InlineKeyboardButton("📢 官方频道", url=PROJECT_INFO['channel']),
        InlineKeyboardButton("💬 交流群组", url=PROJECT_INFO['group'])
    ])
    
    # 添加自定义广告按钮
    ads = db.get_valid_advertisements()
    for ad in ads:
        buttons.append([InlineKeyboardButton(ad.title, url=ad.url)])
    
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    
    await context.bot.send_message(chat_id, notice, parse_mode="MarkdownV2", reply_markup=reply_markup)

async def ban_user_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, message, result):
    """禁言用户并发送通知"""
    from telegram import ChatPermissions
    
    await message.delete()
    
    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user.id,
        permissions=ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False
        )
    )
    
    await send_ban_notice(context, chat_id, user, result)
    logger.info(f"🚫 [AI Anti-Spam Bot] Banned user {user.id} in chat {chat_id}, score: {result.score} | Project: {PROJECT_INFO['repo']}")


# ============ 消息处理 ============

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理文本消息"""
    message = update.message
    user = message.from_user
    chat_id = message.chat_id

    if await is_chat_admin(chat_id, user.id, context):
        return

    db_user = db.get_user(user.id, chat_id)
    if not db_user:
        db_user = UserInfo(
            user_id=user.id,
            chat_id=chat_id,
            join_time=datetime.now(),
            message_count=0,
            check_count=0,
            verification_times=0
        )
        db.save_user(db_user)
    
    db.increment_message_count(user.id, chat_id)

    if not need_check(db_user):
        return

    try:
        user_info = build_user_info(user, db_user)
        result = await ai_client.check_text(user_info, message.text)
        
        score_threshold = config.get("strategy.spam_score", 80)
        
        if result.is_spam and result.score >= score_threshold:
            # 是垃圾广告，封禁
            await ban_user_and_notify(context, chat_id, user, message, result)
            stats.record_check('banned')
        else:
            # 不是垃圾广告，增加验证通过次数
            db.increment_verification_times(user.id, chat_id)
            stats.record_check('passed')
            logger.info(f"User {user.id} passed check, verification_times increased")
    except Exception as e:
        logger.error(f"❌ AI 检测失败 (用户 {user.id}): {e}", exc_info=True)
        stats.record_check('failed')
        # 失败时不封禁，避免误伤

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理图片消息"""
    message = update.message
    user = message.from_user
    chat_id = message.chat_id

    if await is_chat_admin(chat_id, user.id, context):
        return

    db_user = db.get_user(user.id, chat_id)
    if not db_user:
        db_user = UserInfo(
            user_id=user.id,
            chat_id=chat_id,
            join_time=datetime.now(),
            message_count=0,
            check_count=0,
            verification_times=0
        )
        db.save_user(db_user)
    
    db.increment_message_count(user.id, chat_id)

    if not need_check(db_user):
        return

    try:
        photo = message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode()}"

        user_info = build_user_info(user, db_user)
        result = await ai_client.check_image(user_info, image_base64)
        
        score_threshold = config.get("strategy.spam_score", 80)
        if result.is_spam and result.score >= score_threshold:
            await ban_user_and_notify(context, chat_id, user, message, result)
            stats.record_check('banned')
        else:
            db.increment_verification_times(user.id, chat_id)
            stats.record_check('passed')
    except Exception as e:
        logger.error(f"❌ 图片检测失败 (用户 {user.id}): {e}", exc_info=True)
        stats.record_check('failed')
        # 失败时不封禁，避免误伤

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理贴纸消息"""
    message = update.message
    user = message.from_user
    chat_id = message.chat_id

    if await is_chat_admin(chat_id, user.id, context):
        return

    db_user = db.get_user(user.id, chat_id)
    if not db_user:
        db_user = UserInfo(
            user_id=user.id,
            chat_id=chat_id,
            join_time=datetime.now(),
            message_count=0,
            check_count=0,
            verification_times=0
        )
        db.save_user(db_user)
    
    db.increment_message_count(user.id, chat_id)

    if not need_check(db_user):
        return

    try:
        file = await context.bot.get_file(message.sticker.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = f"data:image/webp;base64,{base64.b64encode(image_bytes).decode()}"

        user_info = build_user_info(user, db_user)
        result = await ai_client.check_image(user_info, image_base64)
        
        score_threshold = config.get("strategy.spam_score", 80)
        if result.is_spam and result.score >= score_threshold:
            await ban_user_and_notify(context, chat_id, user, message, result)
            stats.record_check('banned')
        else:
            db.increment_verification_times(user.id, chat_id)
            stats.record_check('passed')
    except Exception as e:
        logger.error(f"❌ 贴纸检测失败 (用户 {user.id}): {e}", exc_info=True)
        stats.record_check('failed')
        # 失败时不封禁，避免误伤


# ============ 成员变动 ============

async def handle_bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 Bot 被添加到群组"""
    chat_member = update.my_chat_member
    new_status = chat_member.new_chat_member.status
    old_status = chat_member.old_chat_member.status
    chat = chat_member.chat
    
    # Bot 被添加到群组（从非成员变为成员）
    if old_status in [ChatMember.LEFT, ChatMember.BANNED] and new_status == ChatMember.MEMBER:
        welcome_msg = (
            "👋 你好！我已加入群组\n\n"
            "🛡️ 我是由狼哥 @luoyanglang 开发的 AI 反垃圾广告机器人，可以自动识别、删除并封禁发送垃圾广告的用户\n\n"
            "⚠️ 请先将我设为管理员\n"
            "需要的权限：\n"
            "• 删除消息\n"
            "• 封禁用户\n\n"
            "✅ 设置完成后，我将自动开始保护群组\n\n"
            "💡 管理员可使用 /admin 查看管理面板\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 官方项目：{PROJECT_INFO['repo']}\n"
            f"💬 交流群组：{PROJECT_INFO['group']}"
        )
        
        try:
            sent_message = await context.bot.send_message(chat.id, welcome_msg)
            logger.info(f"Bot added to group {chat.id} ({chat.title}), welcome message will be deleted in 30s")
            
            # 使用 job_queue 延迟删除消息（比 asyncio.create_task 更可靠）
            async def delete_welcome_message(ctx: ContextTypes.DEFAULT_TYPE):
                try:
                    await ctx.bot.delete_message(chat.id, sent_message.message_id)
                    logger.info(f"Deleted welcome message in group {chat.id}")
                except Exception as e:
                    logger.warning(f"Failed to delete welcome message in {chat.id}: {e}")
            
            context.application.job_queue.run_once(delete_welcome_message, 30)
            
        except Exception as e:
            logger.error(f"Failed to send welcome message to {chat.id}: {e}")
    
    # Bot 被提升为管理员
    elif old_status == ChatMember.MEMBER and new_status == ChatMember.ADMINISTRATOR:
        admin_msg = (
            "✅ 已成为管理员！\n\n"
            "🛡️ 我现在开始保护群组，自动识别并封禁发送垃圾广告的用户\n\n"
            "💡 管理员可使用 /admin 查看管理面板\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 官方项目：{PROJECT_INFO['repo']}\n"
            f"📢 官方频道：{PROJECT_INFO['channel']}\n"
            f"💬 交流群组：{PROJECT_INFO['group']}"
        )
        
        try:
            await context.bot.send_message(chat.id, admin_msg)
            logger.info(f"Bot promoted to admin in group {chat.id} ({chat.title})")
        except Exception as e:
            logger.error(f"Failed to send admin promotion message to {chat.id}: {e}")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新成员加入"""
    chat_member = update.chat_member
    if chat_member.new_chat_member.status == ChatMember.MEMBER:
        user = chat_member.new_chat_member.user
        chat_id = chat_member.chat.id
        
        db_user = UserInfo(
            user_id=user.id,
            chat_id=chat_id,
            join_time=datetime.now(),
            message_count=0,
            check_count=0,
            verification_times=0
        )
        db.save_user(db_user)
        logger.info(f"New member {user.id} joined chat {chat_id}")

# ============ 广告管理命令 ============

async def cmd_add_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    添加广告按钮
    格式: /add_ad 标题|链接|过期时间|权重
    例如: /add_ad 官方频道|https://t.me/channel|2099-01-01 00:00:00|100
    """
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ 仅超级管理员可用")
        return
    
    if not context.args:
        await update.message.reply_text(
            "📝 添加广告按钮\n\n"
            "格式: /add_ad 标题|链接|过期时间|权重\n\n"
            "示例:\n"
            "/add_ad 官方频道|https://t.me/channel|2099-01-01 00:00:00|100\n\n"
            "说明:\n"
            "• 权重越大越靠前\n"
            "• 过期时间格式: YYYY-MM-DD HH:MM:SS"
        )
        return
    
    try:
        payload = " ".join(context.args)
        parts = payload.split("|")
        if len(parts) != 4:
            await update.message.reply_text("❌ 格式错误，需要4个参数")
            return
        
        title, url, validity_str, sort_str = parts
        validity = datetime.strptime(validity_str.strip(), "%Y-%m-%d %H:%M:%S")
        sort = int(sort_str.strip())
        
        ad = Advertisement(
            title=title.strip(),
            url=url.strip(),
            sort=sort,
            validity_period=validity
        )
        
        ad_id = db.add_advertisement(ad)
        await update.message.reply_text(f"✅ 广告添加成功！ID: {ad_id}")
        
        # 显示所有广告
        await cmd_all_ad(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ 添加失败: {str(e)}")

async def cmd_all_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有广告"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ 仅超级管理员可用")
        return
    
    ads = db.get_all_advertisements()
    if not ads:
        await update.message.reply_text("📭 暂无广告")
        return
    
    msg = "📋 所有广告：\n\n"
    for ad in ads:
        validity_str = ad.validity_period.strftime("%Y-%m-%d %H:%M") if ad.validity_period else "永久"
        created_str = ad.created_at.strftime("%Y-%m-%d %H:%M") if ad.created_at else "未知"
        msg += f"ID: {ad.id}\n"
        msg += f"标题: {ad.title}\n"
        msg += f"链接: {ad.url}\n"
        msg += f"权重: {ad.sort}\n"
        msg += f"过期: {validity_str}\n"
        msg += f"创建: {created_str}\n"
        msg += "---\n"
    
    await update.message.reply_text(msg)

async def cmd_del_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    删除广告
    格式: /del_ad <ID>
    """
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ 仅超级管理员可用")
        return
    
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("格式: /del_ad <广告ID>")
        return
    
    try:
        ad_id = int(context.args[0])
        db.delete_advertisement(ad_id)
        await update.message.reply_text(f"✅ 广告 {ad_id} 已删除")
        await cmd_all_ad(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ 删除失败: {str(e)}")

# ============ 其他管理命令 ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    await update.message.reply_text(get_start_message())

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /admin 命令"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == "private":
        if not is_owner(user_id):
            await update.message.reply_text("⚠️ 无权限")
            return
    else:
        if not await is_chat_admin(chat_id, user_id, context):
            await update.message.reply_text("⚠️ 仅群管理员可用")
            return

    model = config.get("ai_model", "unknown")
    score = config.get("strategy.spam_score", 80)
    
    msg = (
        f"⚙️ 管理面板\n\n"
        f"🤖 当前模型: {model}\n"
        f"📊 封禁阈值: {score}分\n"
        f"📅 检测天数: {config.get('strategy.joined_days', 3)}天\n"
        f"💬 最少发言: {config.get('strategy.min_messages', 3)}条\n"
        f"✅ 验证次数限制: {config.get('strategy.verification_times', 0)}\n\n"
        f"💡 管理命令：\n"
        f"• /unban <用户ID> - 解禁用户\n"
    )
    
    if is_owner(user_id):
        msg += (
            f"\n🎯 超级管理员命令：\n"
            f"• /add_ad - 添加广告按钮\n"
            f"• /all_ad - 查看所有广告\n"
            f"• /del_ad <ID> - 删除广告\n"
            f"• /stats - 查看运行统计"
        )
    
    await update.message.reply_text(msg)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看运行统计（仅超级管理员）"""
    user_id = update.effective_user.id
    
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ 仅超级管理员可用")
        return
    
    s = stats.get_stats()
    uptime_hours = s['uptime_seconds'] // 3600
    uptime_mins = (s['uptime_seconds'] % 3600) // 60
    
    msg = (
        f"📊 运行统计\n\n"
        f"⏱️ 运行时长: {uptime_hours}小时 {uptime_mins}分钟\n"
        f"🔍 总检测次数: {s['checks_total']}\n"
        f"✅ 通过: {s['checks_passed']}\n"
        f"🚫 封禁: {s['checks_banned']}\n"
        f"❌ 失败: {s['checks_failed']}\n"
    )
    
    if s['checks_total'] > 0:
        ban_rate = (s['checks_banned'] / s['checks_total']) * 100
        msg += f"\n📈 封禁率: {ban_rate:.1f}%"
    
    await update.message.reply_text(msg)

async def handle_unban_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理解除禁言按钮点击"""
    from telegram import ChatPermissions
    
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    if not await is_chat_admin(chat_id, user_id, context):
        await query.answer("⚠️ 仅群管理员可用", show_alert=True)
        return
    
    callback_data = query.data
    if not callback_data.startswith("unban_"):
        return
    
    target_user_id = int(callback_data.split("_")[1])
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            )
        )
        
        # 删除封禁消息（Go 版本的功能）
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"删除封禁消息失败: {e}")
        
        # 发送解禁通知（Go 版本的功能）
        admin_name = query.from_user.first_name or "管理员"
        notice = f"✅ 管理员 {admin_name} 已解封用户 [{target_user_id}](tg://user?id={target_user_id})"
        await context.bot.send_message(chat_id, notice, parse_mode="Markdown")
        
        await query.answer("✅ 解除禁言成功", show_alert=False)
        
        logger.info(f"Unmuted user {target_user_id} in chat {chat_id} by admin {user_id} via button")
    except Exception as e:
        await query.answer(f"❌ 解除禁言失败：{str(e)}", show_alert=True)
        logger.error(f"Failed to unmute user {target_user_id}: {e}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /unban 命令"""
    from telegram import ChatPermissions
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == "private":
        await update.message.reply_text("⚠️ 此命令只能在群组中使用")
        return
    
    if not await is_chat_admin(chat_id, user_id, context):
        await update.message.reply_text("⚠️ 仅群管理员可用")
        return
    
    target_user_id = None
    target_user_name = None
    
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        target_user_name = update.message.reply_to_message.from_user.first_name
    elif context.args and len(context.args) > 0:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ 无效的用户ID")
            return
    else:
        await update.message.reply_text(
            "⚠️ 请回复被禁言用户的消息\n\n"
            "或使用：/unban <用户ID>"
        )
        return
    
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            )
        )
        
        if target_user_name:
            await update.message.reply_text(
                f"✅ 已解除禁言\n\n"
                f"用户：{target_user_name}\n"
                f"ID：{target_user_id}"
            )
        else:
            await update.message.reply_text(
                f"✅ 已解除禁言\n\n"
                f"用户ID：{target_user_id}"
            )
        
        logger.info(f"Unmuted user {target_user_id} in chat {chat_id} by admin {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ 解除禁言失败：{str(e)}")
        logger.error(f"Failed to unmute user {target_user_id}: {e}")

# ============ 启动 ============

def validate_config():
    """验证必要的配置项"""
    errors = []
    
    # 检查 Telegram Token
    token = config.get("telegram.token")
    if not token:
        errors.append("❌ telegram.token 未配置")
    
    # 检查 AI 模型配置
    ai_model = config.get("ai_model", "openai")
    if ai_model == "openai":
        if not config.get("openai.api_key"):
            errors.append("❌ openai.api_key 未配置")
    elif ai_model == "qwen":
        if not config.get("qwen.api_key"):
            errors.append("❌ qwen.api_key 未配置")
    elif ai_model == "deepseek":
        if not config.get("deepseek.api_key"):
            errors.append("❌ deepseek.api_key 未配置")
    else:
        errors.append(f"❌ 不支持的 AI 模型: {ai_model}")
    
    # 检查超级管理员
    owners = config.get("telegram.owners", [])
    if not owners:
        logger.warning("⚠️ telegram.owners 未配置，广告管理功能将无法使用")
    
    if errors:
        logger.error("配置验证失败：")
        for error in errors:
            logger.error(error)
        logger.error("\n请检查 config.yml 配置文件")
        sys.exit(1)
    
    logger.info("✅ 配置验证通过")

def main():
    # 显示项目信息
    logger.info("=" * 60)
    logger.info(f"🤖 {PROJECT_INFO['name']} - 官方版本")
    logger.info(f"📦 项目地址: {PROJECT_INFO['repo']}")
    logger.info(f"👨‍💻 开发者: {PROJECT_INFO['developer']}")
    logger.info(f"📢 官方频道: {PROJECT_INFO['channel']}")
    logger.info(f"💬 交流群组: {PROJECT_INFO['group']}")
    logger.info(f"🎯 演示 Bot: {PROJECT_INFO['demo_bot']}")
    logger.info("=" * 60)
    
    # 验证配置
    validate_config()
    
    token = config.get("telegram.token")
    
    # 初始化 AI 客户端（带错误处理）
    try:
        global ai_client
        ai_client = create_ai_client()
        logger.info(f"✅ AI 客户端初始化成功: {config.get('ai_model')}")
    except Exception as e:
        logger.error(f"❌ AI 客户端初始化失败: {e}")
        sys.exit(1)

    import os
    api_url = os.getenv("TELEGRAM_API_URL")
    
    builder = Application.builder().token(token)
    if api_url:
        builder = builder.base_url(f"{api_url}/bot")
        builder = builder.base_file_url(f"{api_url}/file/bot")
        logger.info(f"Using custom Telegram API: {api_url}")
    
    app = builder.build()

    # 注册处理器
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("stats", cmd_stats))
    
    # 广告管理命令
    app.add_handler(CommandHandler("add_ad", cmd_add_ad))
    app.add_handler(CommandHandler("all_ad", cmd_all_ad))
    app.add_handler(CommandHandler("del_ad", cmd_del_ad))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(ChatMemberHandler(handle_bot_added_to_group, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(handle_unban_button, pattern="^unban_"))

    logger.info("🚀 Bot 启动中...")
    logger.info(f"📊 检测策略: 加入{config.get('strategy.joined_days')}天内 | 发言{config.get('strategy.min_messages')}条内 | 评分>{config.get('strategy.spam_score')}分")
    logger.info(f"💡 如果本项目对您有帮助，请给项目一个 Star: {PROJECT_INFO['repo']}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
