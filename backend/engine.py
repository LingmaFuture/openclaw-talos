"""
AI 原生心理博弈社交推理游戏 - 极简 MVP
============================================

架构说明：
---------
本系统采用"心理模型 + LLM表达层"的双层架构：
- 心理模型：纯数值计算，控制所有决策（投票、攻击、信任）
- LLM表达层：仅根据心理状态生成自然语言发言

核心设计原则：
1. 决策逻辑由数值心理模型控制，LLM仅生成文本
2. 使用OpenRouter API调用大模型
3. API key从环境变量读取
4. 单文件Python实现
5. 严格控制token使用

心理模型设计：
-------------
每个AI角色拥有：
- trust_scores: 对他人的信任度 (0-1)
- suspicion_scores: 对他人的怀疑度 (0-1)
- emotional_state: 情绪状态 (anger, fear, confidence)
- memory_log: 结构化事件记忆

投票决策公式：
vote_target = argmax(suspicion * suspicion_weight + anger * anger_bias - trust * trust_weight)

狼人夜间决策：
优先击杀：高怀疑值者 或 高影响力角色
避免击杀：高度信任者
"""

import os
import json
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import requests


# ==================== 配置 ====================
class Config:
    """全局配置"""
    # OpenRouter API配置
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-haiku")
    
    # 游戏配置
    NUM_DAYS = 5  # 最大天数
    NUM_AGENTS = 6  # 1人类 + 5 AI
    
    # 心理权重配置
    SUSPICION_WEIGHT = 1.5  # 怀疑权重
    TRUST_WEIGHT = 1.0  # 信任权重
    ANGER_BIAS = 0.5  # 愤怒偏差
    FEAR_FACTOR = 0.3  # 恐惧因子
    CONFIDENCE_FACTOR = 0.2  # 自信因子
    
    # 发言配置
    MAX_TOKENS = 150  # 限制LLM输出token
    TEMPERATURE = 0.7  # LLM温度


# ==================== 数据结构 ====================
class Role(Enum):
    VILLAGER = "villager"
    WOLF = "wolf"


class GamePhase(Enum):
    DAY_DISCUSSION = "day_discussion"
    VOTING = "voting"
    NIGHT_ACTION = "night_action"
    GAME_OVER = "game_over"


@dataclass
class EmotionalState:
    """情绪状态"""
    anger: float = 0.0  # 愤怒值
    fear: float = 0.0   # 恐惧值
    confidence: float = 0.5  # 自信度
    
    def to_dict(self) -> Dict:
        return {
            "anger": round(self.anger, 3),
            "fear": round(self.fear, 3),
            "confidence": round(self.confidence, 3)
        }


@dataclass
class MemoryEvent:
    """记忆事件"""
    event_type: str  # e.g., "accused", "defended", "voted", "killed"
    target: str
    source: str
    impact: float  # 心理影响强度
    turn: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return {
            "event_type": self.event_type,
            "target": self.target,
            "source": self.source,
            "impact": round(self.impact, 3),
            "turn": self.turn,
            "timestamp": self.timestamp
        }


# ==================== LLM 接口模块 ====================
class LLMInterface:
    """
    LLM表达层接口
    
    职责：
    - 根据心理状态生成自然语言发言
    - 控制prompt长度和token使用
    - 可插拔设计，易于更换模型
    """
    
    def __init__(self, api_key: str = None, model_name: str = None):
        self.api_key = api_key or Config.OPENROUTER_API_KEY
        self.model_name = model_name or Config.OPENROUTER_MODEL
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
    
    def _build_prompt(self, agent, visible_state: Dict) -> List[Dict]:
        """构建LLM prompt - 精简版"""
        
        # 提取关键信息
        emotion = agent.emotional_state
        top_suspicions = sorted(
            agent.suspicion_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        recent_memory = agent.memory_log[-2:] if agent.memory_log else []
        
        # 构建系统提示
        system_prompt = f"""你是{agent.name}，一个{agent.role.value}。
你的性格：{agent.personality}
当前情绪状态：
- 愤怒: {emotion.anger:.2f}
- 恐惧: {emotion.fear:.2f}
- 自信: {emotion.confidence:.2f}

规则：
1. 根据你的心理状态和怀疑对象发言
2. 不要暴露你的真实身份（如果是狼人）
3. 发言要符合你的性格特点
4. 简洁有力，不说废话
5. 只谈游戏相关话题"""
        
        # 构建上下文
        context_parts = []
        
        # 添加主要怀疑对象
        if top_suspicions:
            suspects = ", ".join([f"{name}({score:.2f})" for name, score in top_suspicions])
            context_parts.append(f"当前怀疑: {suspects}")
        
        # 添加游戏阶段信息
        phase = visible_state.get("phase", "讨论")
        context_parts.append(f"阶段: {phase}")
        
        # 添加人类玩家信息
        if "human_player" in visible_state:
            context_parts.append(f"人类玩家: {visible_state['human_player']}")
        
        user_prompt = f"""
当前情况：{', '.join(context_parts)}

请生成一句简短的发言（20-50字），表达你的怀疑或观点。不要说"我认为"，直接说内容。
"""
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    
    def generate_statement(self, agent, visible_state: Dict) -> str:
        """生成发言文本"""
        
        if not self.api_key:
            # 无API key时使用规则生成
            return self._fallback_statement(agent, visible_state)
        
        try:
            messages = self._build_prompt(agent, visible_state)
            
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/openclaw-talos",
                },
                json={
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": Config.MAX_TOKENS,
                    "temperature": Config.TEMPERATURE,
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                return content.strip()
            else:
                print(f"LLM API错误: {response.status_code}")
                return self._fallback_statement(agent, visible_state)
                
        except Exception as e:
            print(f"LLM调用异常: {e}")
            return self._fallback_statement(agent, visible_state)
    
    def _fallback_statement(self, agent, visible_state: Dict) -> str:
        """备用生成策略 - 基于规则"""
        phase = visible_state.get("phase", "讨论")
        
        # 找最怀疑的人
        if agent.suspicion_scores:
            most_suspicious = max(agent.suspicion_scores.items(), key=lambda x: x[1])
            target = most_suspicious[0]
        else:
            target = "大家"
        
        # 根据角色和情绪生成
        if agent.role == Role.WOLF:
            templates = [
                f"我觉得{target}的行为很可疑，需要重点关注。",
                f"{target}的发言暴露了什么，大家怎么看？",
                f"我建议今天投{target}，直觉告诉我不太对。",
            ]
        else:
            templates = [
                f"{target}今天发言不多，我有点怀疑。",
                f"我注意到{target}的反应很奇怪。",
                f"大家有没有觉得{target}哪里不对劲？",
            ]
        
        return random.choice(templates)


# ==================== Agent 类 ====================
class Agent:
    """
    AI游戏角色
    
    核心职责：
    - 维护心理状态数值
    - 记录结构化记忆
    - 根据心理模型做出决策
    """
    
    def __init__(self, name: str, role: Role, personality: str, is_human: bool = False):
        self.name = name
        self.role = role
        self.personality = personality
        self.is_human = is_human
        
        # 心理状态
        self.trust_scores: Dict[str, float] = {}
        self.suspicion_scores: Dict[str, float] = {}
        self.emotional_state = EmotionalState()
        self.memory_log: List[MemoryEvent] = []
        
        # 游戏状态
        self.alive = True
        self.vote_count = 0
        self.influence = 1.0  # 影响力分数
        
        # 初始化信任/怀疑分数
        self._init_scores()
    
    def _init_scores(self):
        """初始化信任和怀疑分数"""
        base_trust = 0.3 if self.role == Role.WOLF else 0.5
        for _ in range(5):  # 5个其他角色
            self.trust_scores[self.name] = random.uniform(0.1, 0.3)
            self.suspicion_scores[self.name] = random.uniform(0.1, 0.3)
    
    def update_psychology(self, event_type: str, source: str, target: str, impact: float):
        """更新心理状态"""
        # 记忆事件
        event = MemoryEvent(
            event_type=event_type,
            source=source,
            target=target,
            impact=impact,
            turn=len(self.memory_log)
        )
        self.memory_log.append(event)
        
        # 限制记忆长度
        if len(self.memory_log) > 20:
            self.memory_log = self.memory_log[-15:]
        
        # 数值更新逻辑
        if event_type == "accused":
            # 被指控：增加愤怒和怀疑
            self.emotional_state.anger += impact * 0.3
            self.suspicion_scores[source] = min(1.0, self.suspicion_scores.get(source, 0) + impact * 0.2)
        
        elif event_type == "defended":
            # 被辩护：增加信任
            self.trust_scores[source] = min(1.0, self.trust_scores.get(source, 0) + impact * 0.2)
        
        elif event_type == "voted":
            # 被投票：大幅增加愤怒
            self.emotional_state.anger += impact * 0.5
            self.emotional_state.confidence = max(0.1, self.emotional_state.confidence - 0.1)
        
        elif event_type == "killed":
            # 被杀：增加恐惧
            self.emotional_state.fear += impact * 0.4
        
        elif event_type == "rumor":
            # 传言：影响信任或怀疑
            if impact > 0:
                self.suspicion_scores[target] = min(1.0, self.suspicion_scores.get(target, 0) + impact * 0.15)
            else:
                self.trust_scores[target] = min(1.0, self.trust_scores.get(target, 0) + abs(impact) * 0.15)
        
        # 恐惧影响怀疑
        self.emotional_state.fear = min(1.0, self.emotional_state.fear)
        self.emotional_state.anger = min(1.0, self.emotional_state.anger)
        self.emotional_state.confidence = max(0.0, min(1.0, self.emotional_state.confidence))
    
    def make_vote_decision(self, alive_players: List[str]) -> str:
        """
        投票决策 - 纯数值计算
        
        公式: vote_target = argmax(suspicion * suspicion_weight + anger * anger_bias - trust * trust_weight)
        """
        scores = {}
        
        for player in alive_players:
            if player == self.name:
                continue
            
            suspicion = self.suspicion_scores.get(player, 0.3)
            trust = self.trust_scores.get(player, 0.3)
            
            # 计算投票分数
            vote_score = (
                suspicion * Config.SUSPICION_WEIGHT +
                self.emotional_state.anger * Config.ANGER_BIAS -
                trust * Config.TRUST_WEIGHT
            )
            
            # 添加小幅随机因子（模拟人类的不理性）
            vote_score += random.uniform(-0.1, 0.1)
            
            scores[player] = vote_score
        
        if not scores:
            return self.name
        
        # 返回最高分玩家
        return max(scores.items(), key=lambda x: x[1])[0]
    
    def wolf_night_action(self, alive_players: List[str]) -> Optional[str]:
        """
        狼人夜间决策
        
        策略：
        1. 优先杀：高度怀疑自己的人 或 高影响力角色
        2. 避免杀：高度信任自己的人
        """
        if self.role != Role.WOLF or not self.alive:
            return None
        
        candidates = [p for p in alive_players if p != self.name]
        if not candidates:
            return None
        
        best_target = None
        best_score = float('-inf')
        
        for player in candidates:
            # 获取该玩家的信任和怀疑
            trust = self.trust_scores.get(player, 0.3)
            suspicion_on_me = player in self.suspicion_scores and self.suspicion_scores[player] > 0.5
            
            # 基础分数：低信任 = 高风险
            score = -trust * 2.0
            
            # 加分：如果该玩家怀疑我
            if suspicion_on_me:
                score += 0.5
            
            # 随机因子
            score += random.uniform(-0.2, 0.2)
            
            if score > best_score:
                best_score = score
                best_target = player
        
        return best_target
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "role": self.role.value,
            "alive": self.alive,
            "emotional_state": self.emotional_state.to_dict(),
            "top_suspicions": sorted(
                [(k, v) for k, v in self.suspicion_scores.items() if k != self.name],
                key=lambda x: x[1],
                reverse=True
            )[:3],
            "influence": self.influence
        }


# ==================== GameState 管理器 ====================
class GameState:
    """
    游戏状态管理器
    
    职责：
    - 管理游戏阶段转换
    - 协调各模块交互
    - 维护全局游戏状态
    """
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.phase = GamePhase.DAY_DISCUSSION
        self.day = 1
        self.turn = 0
        self.vote_results: Dict[str, int] = {}
        self.night_kill: Optional[str] = None
        self.winner: Optional[str] = None
        self.llm_interface = LLMInterface()
        
        # 初始化角色
        self._init_agents()
    
    def _init_agents(self):
        """初始化AI角色"""
        roles = [Role.WOLF] + [Role.VILLAGER] * 4
        random.shuffle(roles)
        
        personalities = [
            "理性分析型，说话有逻辑但冷淡",
            "热情激进，容易激动",
            "谨慎观察型，很少发言但观察细致",
            "社交达人，喜欢建立联盟",
            "怀疑一切，对谁都不完全信任",
        ]
        
        names = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
        
        for i, (name, role) in enumerate(zip(names, roles)):
            personality = personalities[i] if i < len(personalities) else "普通村民"
            self.agents[name] = Agent(name, role, personality)
        
        # 人类玩家
        self.human_player = "Player"
        self.agents["Player"] = Agent("Player", Role.VILLAGER, "人类玩家", is_human=True)
    
    def get_alive_players(self) -> List[str]:
        return [name for name, agent in self.agents.items() if agent.alive]
    
    def get_wolf_count(self) -> int:
        return sum(1 for a in self.agents.values() if a.role == Role.WOLF and a.alive)
    
    def get_villager_count(self) -> int:
        return sum(1 for a in self.agents.values() if a.role == Role.VILLAGER and a.alive)
    
    def check_game_end(self) -> bool:
        """检查游戏是否结束"""
        wolves = self.get_wolf_count()
        villagers = self.get_villager_count()
        
        if wolves == 0:
            self.winner = "villagers"
            self.phase = GamePhase.GAME_OVER
            return True
        elif wolves >= villagers:
            self.winner = "wolves"
            self.phase = GamePhase.GAME_OVER
            return True
        elif self.day > Config.NUM_DAYS:
            self.winner = "wolves"  # 超时狼人获胜
            self.phase = GamePhase.GAME_OVER
            return True
        
        return False


# ==================== 游戏主逻辑 ====================
class PsychologicalGame:
    """
    心理博弈社交推理游戏主控类
    """
    
    def __init__(self):
        self.game_state = GameState()
    
    def run_day_discussion(self):
        """讨论阶段"""
        print(f"\n{'='*60}")
        print(f"第 {self.game_state.day} 天 - 讨论阶段")
        print(f"{'='*60}")
        
        alive = self.game_state.get_alive_players()
        random.shuffle(alive)
        
        for speaker in alive:
            agent = self.game_state.agents[speaker]
            if not agent.alive:
                continue
            
            # 生成发言
            visible_state = {
                "phase": "讨论",
                "day": self.game_state.day,
                "human_player": self.game_state.human_player if speaker != "Player" else None
            }
            
            statement = self.game_state.llm_interface.generate_statement(agent, visible_state)
            print(f"\n【{agent.name}】（{agent.role.value}）说：")
            print(f"  「{statement}」")
            
            # 更新其他人的心理状态
            for other_name in alive:
                if other_name == speaker or other_name == agent.name:
                    continue
                
                other = self.game_state.agents[other_name]
                
                # 根据发言内容更新心理
                # 简单规则：如果发言中提到某人的名字，增加对该人的怀疑
                for name in self.game_state.agents:
                    if name in statement and name != speaker:
                        # 被提到的人增加怀疑
                        impact = random.uniform(0.1, 0.3)
                        other.update_psychology("accused", speaker, name, impact)
                        # 被提到的人增加愤怒
                        self.game_state.agents[name].update_psychology("attacked", speaker, speaker, impact * 0.5)
            
            # rumor effect - 随机影响
            if random.random() < 0.3:
                rumor_target = random.choice([p for p in alive if p != speaker])
                rumor_impact = random.uniform(-0.2, 0.3)
                agent.update_psychology("rumor", "rumor", rumor_target, rumor_impact)
            
            self.game_state.turn += 1
    
    def run_voting(self):
        """投票阶段"""
        print(f"\n{'='*60}")
        print(f"第 {self.game_state.day} 天 - 投票阶段")
        print(f"{'='*60}")
        
        alive = self.game_state.get_alive_players()
        votes: Dict[str, str] = {}
        
        for name in alive:
            agent = self.game_state.agents[name]
            if not agent.alive:
                continue
            
            target = None
            
            if agent.is_human:
                # 人类玩家输入 - 支持非交互式
                print(f"\n当前存活：{', '.join(alive)}")
                try:
                    user_input = input(f"【{name}】请投票（输入名字）：").strip()
                    if user_input and user_input in alive:
                        target = user_input
                    else:
                        print(f"无效投票，自动跳过（输入：'{user_input}'）")
                except (EOFError, OSError):
                    print(f"非交互式模式，自动跳过投票")
                    continue
            else:
                # AI投票
                target = agent.make_vote_decision(alive)
            
            if target:
                votes[name] = target
                print(f"【{name}】投票给了 {target}")
                
                # 被投票者更新状态
                if target in self.game_state.agents:
                    self.game_state.agents[target].vote_count += 1
                    self.game_state.agents[target].update_psychology(
                        "voted", name, target, 0.3
                    )
        
        # 统计票数
        vote_counts: Dict[str, int] = {}
        for voter, target in votes.items():
            vote_counts[target] = vote_counts.get(target, 0) + 1
        
        print(f"\n投票结果：{vote_counts}")
        
        # 找出最高票者
        if vote_counts:
            max_votes = max(vote_counts.values())
            candidates = [p for p, c in vote_counts.items() if c == max_votes]
            
            if len(candidates) == 1:
                eliminated = candidates[0]
                print(f"\n⚠️  {eliminated} 被投票淘汰！")
                
                eliminated_agent = self.game_state.agents[eliminated]
                eliminated_agent.alive = False
                
                # 公布身份
                role_name = "狼人" if eliminated_agent.role == Role.WOLF else "村民"
                print(f"  真实身份：{role_name}")
                
                # 其他人更新心理
                for name, agent in self.game_state.agents.items():
                    if name != eliminated and agent.alive:
                        agent.update_psychology("eliminated", eliminated, eliminated, 0.2)
    
    def run_night_action(self):
        """夜晚阶段"""
        print(f"\n{'='*60}")
        print(f"第 {self.game_state.day} 天 - 夜晚阶段")
        print(f"{'='*60}")
        
        alive = self.game_state.get_alive_players()
        wolves = [name for name in alive 
                 if self.game_state.agents[name].role == Role.WOLF]
        
        if not wolves:
            return
        
        # 狼人决策
        kill_target = None
        for wolf_name in wolves:
            agent = self.game_state.agents[wolf_name]
            target = agent.wolf_night_action(alive)
            
            if target:
                kill_target = target
                print(f"【{wolf_name}】（狼人）决定袭击 {target}")
                break
        
        if kill_target:
            self.game_state.night_kill = kill_target
            victim = self.game_state.agents[kill_target]
            victim.alive = False
            
            print(f"\n🌙 夜里，{kill_target} 被发现死亡！")
            print(f"  真实身份：{'狼人' if victim.role == Role.WOLF else '村民'}")
            
            # 其他人更新心理
            for name, agent in self.game_state.agents.items():
                if name != kill_target and agent.alive:
                    agent.update_psychology("killed", kill_target, kill_target, 0.4)
    
    def print_status(self):
        """打印当前状态"""
        print(f"\n{'='*60}")
        print("游戏状态概览")
        print(f"{'='*60}")
        
        alive = self.game_state.get_alive_players()
        print(f"存活玩家：{', '.join(alive)}")
        print(f"狼人数量：{self.game_state.get_wolf_count()}")
        print(f"村民数量：{self.game_state.get_villager_count()}")
        
        print("\n玩家心理状态：")
        for name in alive:
            agent = self.game_state.agents[name]
            emotion = agent.emotional_state
            top_susp = sorted(agent.suspicion_scores.items(), 
                            key=lambda x: x[1], reverse=True)[:2]
            
            print(f"  {name}：愤怒={emotion.anger:.2f}, "
                  f"恐惧={emotion.fear:.2f}, 自信={emotion.confidence:.2f}")
            if top_susp:
                susp_str = ", ".join([f"{n}({s:.2f})" for n, s in top_susp if n != name])
                print(f"    主要怀疑：{susp_str}")
    
    def run(self):
        """主游戏循环"""
        print("🐺👥 AI心理博弈社交推理游戏 开始！")
        print("\n规则：")
        print("- 5名AI角色：4村民 + 1狼人（隐藏）")
        print("- 你扮演第6名玩家（村民）")
        print("- 白天讨论并投票，夜晚狼人行动")
        print("- 目标是找出并投票淘汰所有狼人")
        
        # 显示狼人（调试用，实际游戏应该隐藏）
        for name, agent in self.game_state.agents.items():
            if agent.role == Role.WOLF:
                print(f"\n[系统] 狼人是：{name}（这是内部信息，不要声张！）")
                break
        
        while not self.game_state.check_game_end():
            # 打印状态
            self.print_status()
            
            # 讨论阶段
            self.run_day_discussion()
            
            if self.game_state.check_game_end():
                break
            
            # 投票阶段
            self.run_voting()
            
            if self.game_state.check_game_end():
                break
            
            # 夜晚阶段
            self.run_night_action()
            
            if self.game_state.check_game_end():
                break
            
            self.game_state.day += 1
            
            # 非交互式模式下跳过暂停
            try:
                input(f"\n按 Enter 进入第 {self.game_state.day} 天...")
            except (EOFError, OSError):
                pass
        
        # 游戏结束
        print(f"\n{'='*60}")
        print("游戏结束！")
        print(f"{'='*60}")
        
        if self.game_state.winner == "villagers":
            print("🏆 村民获胜！")
        else:
            print("🐺 狼人获胜！")
        
        print("\n游戏记录：")
        for name, agent in self.game_state.agents.items():
            if agent.memory_log:
                print(f"\n{name} 的关键记忆：")
                for event in agent.memory_log[-3:]:
                    print(f"  - {event.event_type}: {event.target} (影响:{event.impact:.2f})")


# ==================== 成本控制建议 ====================
COST_CONTROL_TIPS = """
💰 成本控制建议：
1. 使用低价模型：如 claude-3-haiku 或 deepseek
2. 限制发言长度：MAX_TOKENS=150
3. 减少LLM调用：仅生成关键发言
4. 缓存结果：相似心理状态可复用
5. 本地fallback：无API时使用规则生成

预期成本估算（Claude-3-Haiku）：
- 每次发言：~100 tokens * $0.00025 = ¥0.00018
- 一局游戏（~30次发言）：~¥0.005
- 完全可控且便宜
"""

# ==================== 可扩展方向 ====================
EXTENSION_IDEAS = """
🚀 可扩展升级方向：
1. 多狼人模式：支持2-3个狼人
2. 特殊角色：预言家、猎人、女巫
3. 联盟系统：玩家可结成临时联盟
4. 记忆持久化：跨局保存角色记忆
5. Web界面：添加可视化界面
6. 多人模式：支持多个人类玩家
7. 动态难度：根据玩家水平调整AI策略
8. 语音合成：使用TTS生成语音发言
"""

# ==================== 主程序入口 ====================
if __name__ == "__main__":
    # 打印架构说明
    print(__doc__)
    
    # 运行游戏
    try:
        game = PsychologicalGame()
        game.run()
        
        # 打印建议
        print(COST_CONTROL_TIPS)
        print(EXTENSION_IDEAS)
        
    except KeyboardInterrupt:
        print("\n游戏已中断")
    except Exception as e:
        print(f"\n游戏异常：{e}")
        import traceback
        traceback.print_exc()
