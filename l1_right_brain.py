import json
from openai import OpenAI
from jarvis_utils import network_retry

class RightBrain:
    def __init__(self, api_key):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1", 
            api_key=api_key,
            timeout=30.0  
        )

    @network_retry(max_retries=3, base_delay=2)
    def _safe_api_call(self, model, messages, temperature):
        return self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=1500 
        )

    def set_strategic_plan(self, user_voice_input: str, recent_context: str, organ_whitepaper: str) -> dict:
        prompt = f"""
        你是一个最高级别的 AGI 战略调度与多步规划中心。
        用户的指令可能跨越多个不同的物理环境。你的任务是将其拆解为 1 个或多个【串行任务阶段】，并精准分配物理器官。
        
        【近期对话与阶段求援记录】：
        {recent_context if recent_context else "无"}
        
        【系统当前可用的 Hands 物理器官白皮书】：
        {organ_whitepaper}
        
        【用户当前意图或底层左脑的求援请求】：
        "{user_voice_input}"
        
        【多步规划与路由抽象法则】：
        1. 视神经绑定公式：分配 required_eyes 时，【必须】直接将 Hands 名称中的 "_hands" 替换为 "_eyes"。
        2. 器官互斥定律：需要跨越不同的系统环境（比如寻找文件与编写代码），【必须】拆分为多个串行阶段。
        3. 动态求援接管：如果用户意图是一条【左脑的求援报错】（例如左脑说不知道桌面在哪），你必须立刻规划一个前置阶段，挂载具备相关能力的器官（如 system_hands 去侦察坐标），并将找出的信息通过接力交给下一个阶段。
           
        【强制输出格式与止语铁律】(绝对红线)：
        1. 你【只允许】输出纯 JSON 代码块！在 JSON 的前面和后面【绝对不允许】出现任何一个多余的标点或解释性文字！
        2. "reasoning" 字段【必须极度精简】，限制在 80 个汉字以内，直击要害！
        3. 必须首先输出 reasoning 进行逻辑推理，再输出 tasks 数组。输出纯 JSON：
        {{
          "reasoning": "第一步分析需求；第二步找匹配的器官；第三步决定排期...",
          "tasks":[
            {{
              "macro_goal": "该阶段的具体目标与行动指导（越具体越好）",
              "required_eyes": "推导出的_eyes模块",
              "required_hands": "推导出的_hands模块",
              "left_brain_model": "flash 或 pro"
            }}
          ]
        }}
        """
        response = self._safe_api_call(
            model="xiaomi/mimo-v2.5-pro", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        
        # 🛡️ 增加判空防御
        # --- 将 l1_right_brain.py 的结尾替换为以下代码 ---
        
        content = response.choices[0].message.content
        if not content:
            print("⚠️ [L1 右脑] API 返回内容为空 (None)。")
            return {} 
            
        try:
            import re
            match = re.search(r'\{.*\}', content.strip(), re.DOTALL)
            if not match:
                return {}
                
            json_str = match.group(0)
            # 🧹 暴力清洗：去除大模型最容易犯错的“多余的尾部逗号”
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str) 
            
            return json.loads(json_str)
            
        except Exception as e:
            # 如果解析仍然失败，打印出大模型的原话方便复盘，但系统绝对不崩溃！
            print(f"⚠️ [L1 右脑] JSON 结构破裂解析失败: {e}\n(模型原话): {content}")
            return {} # 温和地返回空字典，Nerve 会自动判断为“路由失败”并回到待机