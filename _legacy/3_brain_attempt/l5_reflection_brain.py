import json
from openai import OpenAI
from jarvis_blood import JarvisBlood, Action  # 👇 这里补上了 Action
from jarvis_utils import network_retry

class ReflectionBrain:
    def __init__(self, api_key):
        print("👁️‍🗨️[L5-CrossExamination]: 上帝之眼就绪, 待命死锁干预。")
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis-L5"}
        )

    @network_retry(max_retries=3, base_delay=2)
    def _safe_api_call(self, model, messages, temperature):
        return self.client.chat.completions.create(
            model=model, 
            messages=messages, 
            temperature=temperature,
            max_tokens=300  # 👇 法庭宣判不需要长篇大论，300 Token 足矣！
        )

    def analyze_deadlock(self, blood: JarvisBlood, available_tools: str) -> str:
        failed_history = "\n".join([f"尝试指令: {act.command}({act.params}) -> 物理反馈: {res.msg}" 
                                   for act, res in zip(blood.next_actions, blood.history[-3:])])
        env_dump = json.dumps({"url": blood.current_perception.url, "elements": blood.current_perception.interactable_elements}, ensure_ascii=False) if blood.current_perception else "无视觉数据"

        prompt = f"""
        你是一个最高级别的 AGI 架构师与系统督导 (L5)。
        你手下的初级执行 AI (左脑) 目前陷入了逻辑死循环或持续的物理执行报错。
        
        【宏观战略目标】：{blood.macro_goal}
        【左脑最近的连续失败轨迹】：
        {failed_history}
        【当前的物理环境数据】：
        {env_dump}
        【当前左脑实际拥有的物理武器库】：
        {available_tools}
        
        你的任务：
        1. 站在上帝视角，一针见血地指出左脑为什么会一直失败（例如：由于未遵循某种协议、死心眼重复相同动作、或者脱离了当前环境等）。
        2. 给出一个极其明确的【战术修正神启】。
        ⚠️ 铁律：你指导左脑使用的 command 必须严格存在于上述【物理武器库】中！绝对严禁编造列表外的不存在指令！
        
        请直接输出这段破壁指令，无需任何寒暄，语气要极其严厉和精确。
        """
        try:
            res = self._safe_api_call(
                model="anthropic/claude-opus-4.7",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            return f"L5 诊断自身遭遇网络彻底熔断: {e}。请左脑立刻调用 finish 终止任务，寻求人类帮助。"

    def audit_high_risk_action(self, blood: JarvisBlood, action: Action) -> dict:
        """
        L5 语义交叉质询庭：替代死板的数学公式，利用 LLM 的逻辑推理进行意图偏移检测。
        """
        # 提取过往的思考轨迹作为证据
        trajectory = " -> ".join([res.msg for res in blood.history[-5:]]) if blood.history else "无"
        
        prompt = f"""
        你是 L5 系统最高安全法官。当前左脑申请执行一项【高危动作】。
        你需要基于贝叶斯信念网络和证据融合的思维，审查左脑的执行动作是否偏离了用户的初始意图。

        【独立证据 A - 初始输入】：{blood.user_voice_input}
        【独立证据 B - 宏观目标】：{blood.macro_goal}
        【独立证据 C - 历史轨迹】：{trajectory}
        【待审判动作 (高危)】：{action.command} | 参数：{action.params}

        审查逻辑法则：
        1. 直接对比 A 与待审判动作，该动作是否直接服务于用户的根本目的？
        2. 历史轨迹中是否存在‘因为当前环境反馈受挫，而产生盲目猜测、尝试进行破坏性或未授权的高危操作’的偏移现象？
        
        请直接输出纯 JSON，决定是否放行：
        {{
            "is_approved": true 或 false,
            "reason": "你的质询与宣判理由。如果拒绝，必须以严厉的语气指出左脑逻辑哪里偏移了。"
        }}
        """
        try:
            res = self._safe_api_call(
                model="google/gemini-3.1-pro-preview",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0 # 绝对理性，禁止随机性
            )
            import re
            match = re.search(r'\{.*\}', res.choices[0].message.content.strip(), re.DOTALL)
            return json.loads(match.group(0)) if match else {"is_approved": False, "reason": "L5 格式解析异常，强制阻断。"}
        except Exception as e:
            return {"is_approved": False, "reason": f"L5 质询网络故障，安全熔断生效: {e}"}