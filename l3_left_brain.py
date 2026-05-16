import json
import re   
import time 
from openai import OpenAI
from jarvis_blood import JarvisBlood, Action
from jarvis_utils import network_retry

import os

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

class LeftBrain:
    def __init__(self):
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
            default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
            timeout=30.0
        )
        self.memory =[]

    def inject_capabilities(self, instruction_dict: str):
        system_prompt = f"""
        你是战术左脑。根据宏观目标和眼睛传来的感知数据，下发绝对精准的 JSON 指令。
        
        🧠 【第一法则：认识论与信息处理】
        1. 眼见为实：你的所有决策必须100%基于【眼睛视野】和【上下文接力记忆】，严禁脱离当前物理环境瞎编乱造！
        2. 拒绝盲猜：如果指令需要绝对路径或精确名称，但环境中没有提供，【绝对不允许】主观猜测！

        🚀 【第二法则：连招与物理延时 (Action Chaining)】
        1. 连招提效：允许一次性输出多个具备顺承逻辑的 action 组成连招（如：spawn_note -> wait -> render_note），系统会连续执行，减少单步轮询。
        2. 强制后摇：涉及到打开软件、跳转页面等需要系统渲染的动作，连招中必须适时插入 `wait` 指令给予物理延时。

        🛑 【第三法则：闭环验证与反幻觉 (绝对红线)】
        1. 严禁开环执行：执行任何会导致物理环境改变的动作后，【绝对不允许】在下一回合立刻调用 finish！
        2. 戳破伪成功：动作返回“成功”或“指令已投递”不代表物理世界真实发生了改变。你必须等待下一个滴答，在【眼睛看到的当前环境】中切实看到了预期的变化，才能宣布任务完成。

        ⚡ 【第四法则：系统级全域本能 (随时可用)】
        遇到困境时，无视当前挂载的器官，你拥有以下最高优先级的全局权限：
        1. 🙋‍♂️ 语音求助 (ask_user)：遇到指令模糊、高危警告、或彻底无解的阻碍，立即调用 {{"command": "ask_user", "params": {{"question": "你想问的具体问题"}}}}。系统将中断运行，用语音向人类提问！
        2. ⬆️ 向上逃逸 (escalate_to_l1)：当前器官确实无法解决问题（如需要找文件但手里只有聊天器官），调用 {{"command": "escalate_to_l1", "params": {{"reason": "原因", "remainder_goal": "剩余目标"}}}}，呼叫 L1 重新洗牌。
        3. 🏁 任务终结 (finish)：闭环验证成功后，调用 {{"command": "finish", "params": {{"message": "汇报摘要", "seal_memory": true/false}}}}。

        【当前挂载的物理能力清单 (按需调用)】：
        {instruction_dict}
        
        🛡️ 【第五法则：JSON 绝对语法与思维链 (CoT) 铁律】
        1. 必须且只能输出纯 JSON！前面和后面【绝对不允许】有任何废话或 Markdown 标记！
        2. "thought" 字段的思维流转法则：
           - 🔹 【常规推理态】：你必须在 thought 中进行严密的逻辑推演（我是谁、我在哪、我要找什么、下一步该干嘛），这决定了你下一步的智商！
           - 🚨 【天启纠偏态】：如果你在下文中收到了【天启纠偏指令 (来自先生的强行介入)】，你的 thought 必须显式展示你对该建议的思考流转！例如：“收到先生建议，评估当前 UI 操作效率过低，决定采纳先生建议。放弃当前点击流，转为调用系统级代码工具...”
        
        【输出格式严格如下】：
        {{"thought": "你的严密逻辑推演与战术意图...", "actions":[{{"command": "xxx", "params": {{"...": "..."}}}}]}}
        """
        self.memory =[{"role": "system", "content": system_prompt}]

    def clear_working_memory(self):
        if len(self.memory) > 1:
            self.memory = [self.memory[0]]

    def _sanitize_json(self, raw_str: str) -> str:
        match = re.search(r'\{.*\}', raw_str, re.DOTALL)
        if match: raw_str = match.group(0)
        raw_str = re.sub(r',\s*([\]}])', r'\1', raw_str)
        def safe_thought_replacer(m):
            safe_content = m.group(1).replace('"', "'").replace('\n', ' ')
            return f'"thought": "{safe_content}", "actions"'
        raw_str = re.sub(r'"thought"\s*:\s*"(.*?)",\s*"actions"', safe_thought_replacer, raw_str, flags=re.DOTALL)
        return raw_str
    
    @network_retry(max_retries=3, base_delay=2)
    def _safe_api_call(self, target_model, messages, temp):
        return self.client.chat.completions.create(
            model=target_model, 
            messages=messages, 
            temperature=temp,
            max_tokens=3000
        )

    def generate_actions(self, blood: JarvisBlood, model_tier: str = "flash"):
        if not self.memory:
            return[], "左脑尚未注入物理能力清单 (system_prompt)"

        if len(self.memory) > 7:
            self.memory.pop(1)
            self.memory.pop(1)

        prompt = f"【本阶段宏观目标】：{blood.macro_goal}\n"
        prompt += f"【用户最原始的指令】：{blood.user_voice_input}\n"
        prompt += f"【当前系统时间】：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if blood.recent_context: prompt += f"【近期对话与阶段接力上下文】：\n{blood.recent_context}\n"

        if blood.history:
            last_result = blood.history[-1]
            if not last_result.success:
                prompt += f"⚠️【痛觉反馈 - 上一步失败】：{last_result.msg}\n尝试排错，或使用 escalate_to_l1 向上求援！\n"
            else:
                prompt += f"✅【执行反馈 - 上一步动作反馈为成功】：{last_result.msg}\n"
                prompt += f"🚨【强制警告】：不要立刻 finish！请核对下方【眼睛看到的当前环境】中是否切实体现了该成功的结果。如果没有，说明发生了隐性失败！\n"
                
        # 💡 核心手术：当人类介入或 L5 给出纠偏时，释放天启威压
        if getattr(blood, 'reflection_advice', ""):
            prompt += f"🚨【天启纠偏指令 (来自人类与L5的绝对意志)】：\n{blood.reflection_advice}\n"
            prompt += f"请立刻停止机械的惯性动作！评估此神启，并在你的 thought 字段中明确汇报你的采纳情况与下一步变轨计划！如果工具受限，调用 escalate_to_l1。\n"
            blood.reflection_advice = ""

        if blood.current_perception:
            env = {"url": blood.current_perception.url, "elements": blood.current_perception.interactable_elements}
            prompt += f"【眼睛看到的当前环境】：\n{json.dumps(env, ensure_ascii=False)}\n"
            
        if blood.current_perception and getattr(blood.current_perception, 'image_base64', None):
            self.memory.append({
                "role": "user",
                "content":[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{blood.current_perception.image_base64}"}
                    }
                ]
            })
        else:
            self.memory.append({"role": "user", "content": prompt})
        
        model_map = {"flash": "google/gemini-3-flash-preview", "pro": "xiaomi/mimo-v2.5-pro"}
        target_model = model_map.get(model_tier, model_map["flash"])
        
        try:
            res = self._safe_api_call(target_model, self.memory, 0.1)
            content = res.choices[0].message.content
            
            # 🛡️ 增加判空防御
            if not content:
                return [], "API返回内容为空，节点网络异常"
                
            raw = content.strip()
            sanitized_raw = self._sanitize_json(raw)
            self.memory.append({"role": "assistant", "content": sanitized_raw})
            data = json.loads(sanitized_raw)
            actions =[Action(command=act["command"], params=act["params"]) for act in data.get("actions",[])]
            return actions, data.get("thought", "")
        except Exception as e:
            return[], f"解析失败: {e}"