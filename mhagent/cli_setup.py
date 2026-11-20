"""首次运行引导与命令行输入处理。

顺序:设置本地口令(提示丢失无法找回)→ 手机号验证码登录 → 展示并确认同意书
→ 可选填写紧急联系人并单独确认授权。

本地口令与手机号登录是两件事:口令用于加密本机数据,登录令牌只用于访问后端;
令牌存在本地加密库,过期就用验证码重新登录,不影响本地数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mhagent.auth_session import AuthSession, TokenPair
from mhagent.consent import ConsentStore, ConsentState
from mhagent.llm.gateway import CodeInvalid, InvalidPhone, TooFrequent
from mhagent.store.crypto import DecryptError
from mhagent.store.db import LocalStore

DEFAULT_CONSENT_TEXT = (
    "欢迎使用本地心理健康助手。请阅读以下说明:\n"
    "- 你的日记、量表结果、练习记录与会话内容只保存在本设备,并使用你设置的口令加密;\n"
    "- 对话内容会经后端网关发送给第三方模型服务(DeepSeek),网关不保存正文;\n"
    "- 高风险且你已单独授权时,会向你的紧急联系人发送一条通知,后端发送后不保存联系方式;\n"
    "- 本产品提供筛查提示与自助支持,不构成诊断,也不能替代专业帮助;\n"
    "- 心理援助热线 12356,急救电话 120。"
)

YES_WORDS = {"y", "yes", "是", "同意", "好", "确认"}
SKIP_WORDS = {"", "跳过", "不填", "否", "n", "no", "没有"}


class SetupAborted(Exception):
    """用户中止或引导失败。"""


@dataclass
class SetupResult:
    store: LocalStore
    session: AuthSession
    phone: str | None
    is_new: bool
    consent: ConsentState

    def close(self) -> None:
        self.store.close()


def _is_yes(answer: str) -> bool:
    return answer.strip().lower() in YES_WORDS


def mask_phone(phone: str) -> str:
    value = str(phone)
    return value[:3] + "****" + value[-4:] if len(value) >= 7 else "***"


class CliSetup:
    """可脚本化测试的首次引导。`auth` 需实现 `send_code` 与 `login`。"""

    def __init__(
        self,
        *,
        data_dir,
        input_fn=input,
        output_fn=print,
        auth=None,
        auth_factory=None,
        consent_client=None,
        consent_factory=None,
        now=None,
    ):
        self.data_dir = Path(data_dir).expanduser()
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.auth = auth
        self.auth_factory = auth_factory
        self.consent_client = consent_client
        self.consent_factory = consent_factory
        self._now = now

    def _say(self, message: str) -> None:
        self.output_fn(message)

    def _ask(self, prompt: str) -> str:
        return str(self.input_fn(prompt)).strip()

    def run(self) -> SetupResult:
        is_existing = (self.data_dir / "meta.json").exists()
        if is_existing:
            self._say("请输入本地口令(用于解密本机数据)。")
        else:
            self._say("首次使用需要设置本地口令。口令丢失后本地数据无法找回,请妥善保管。")
        passphrase = self._ask("本地口令:")
        if not passphrase:
            raise SetupAborted("口令不能为空")

        try:
            store = LocalStore(self.data_dir, passphrase)
        except DecryptError:
            self._say("本地口令错误,原数据没有被修改。请重试,或从加密备份恢复。")
            raise

        session = AuthSession(store)
        consent = ConsentStore(store)
        auth = self.auth_factory(session) if self.auth_factory else self.auth
        consent_client = (
            self.consent_factory(session) if self.consent_factory else self.consent_client
        )

        phone: str | None = None
        is_new = False
        if session.valid():
            phone = store.kv_get("account.phone")
        else:
            phone, is_new = self._login(session, auth)
            previous = store.kv_get("account.phone")
            if previous and previous != phone:
                self._say(
                    f"这台设备上的本地数据属于原账号(尾号 {mask_phone(previous)[-4:]}),"
                    "换手机号登录不会清除或混用这些数据。"
                )
                answer = self._ask("是否继续使用这台设备上的原有数据?(y/n):")
                if not _is_yes(answer):
                    session.clear()
                    store.close()
                    raise SetupAborted("已退出,未切换账号,本地数据保持不变。")

        if not consent.get().version:
            version, text = self._consent_content(consent_client)
            self._say("\n" + text + "\n")
            answer = self._ask(f"是否同意上述条款(版本 {version})?(y/n):")
            if not _is_yes(answer):
                session.clear()
                store.close()
                raise SetupAborted("未同意条款,已退出且未保存任何数据。")
            consent.agree(version)

        if not consent.get().emergency_authorized:
            channel = self._ask("是否填写紧急联系人?(sms/email/跳过):").strip().lower()
            if channel in ("sms", "email"):
                contact = self._ask("请输入紧急联系人的手机号或邮箱:")
                authorized = self._ask("高风险时是否授权通知该联系人?(y/n):")
                if contact:
                    consent.set_emergency_contact(channel, contact, authorized=_is_yes(authorized))

        if phone:
            store.kv_set("account.phone", phone)

        return SetupResult(
            store=store,
            session=session,
            phone=phone,
            is_new=is_new,
            consent=consent.get(),
        )

    def _consent_content(self, consent_client=None) -> tuple[str, str]:
        if consent_client is not None:
            try:
                data = consent_client.get_latest_consent()
                version = str(data.get("version", "v1"))
                text = str(data.get("text") or DEFAULT_CONSENT_TEXT)
                return version, text
            except Exception:
                pass
        return "v1", DEFAULT_CONSENT_TEXT

    def _login(self, session: AuthSession, auth=None) -> tuple[str, bool]:
        if auth is None:
            raise SetupAborted("登录通道未配置")
        failures = 0
        while failures < 3:
            phone = self._ask("手机号:")
            try:
                auth.send_code(phone)
            except InvalidPhone as exc:
                self._say(str(exc))
                continue
            except TooFrequent as exc:
                self._say(str(exc))
                raise SetupAborted("发送验证码过于频繁,请稍后再试") from exc

            code = self._ask("验证码:")
            try:
                tokens = auth.login(phone, code)
            except CodeInvalid:
                failures += 1
                self._say(f"验证码错误,请重新输入({failures}/3)。")
                continue
            except TooFrequent as exc:
                self._say(str(exc))
                raise SetupAborted("操作过于频繁,请稍后再试") from exc

            if isinstance(tokens, TokenPair):
                session.save(tokens)
                is_new = tokens.is_new
            else:
                is_new = False
            if is_new:
                self._say("首次登录已自动注册,获赠 100 积分。")
            return phone, is_new
        raise SetupAborted("验证码连续错误,请稍后再试。")
