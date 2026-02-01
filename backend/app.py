"""
AI心理博弈社交推理游戏 - FastAPI 服务端
==========================================
提供HTTP API + WebSocket事件流
"""

import json
import uuid
import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from engine import (
    Agent, Role, GamePhase, EmotionalState, MemoryEvent,
    Config, LLMInterface, GameState
)

load_dotenv()


# ==================== 数据模型 ====================
class NewGameRequest(BaseModel):
    player_name: str = "Player"


class NewGameResponse(BaseModel):
    game_id: str
    day: int
    phase: str
    players: List[dict]
    your_role: str


class PlayerSayRequest(BaseModel):
    statement: str


class PlayerVoteRequest(BaseModel):
    target: str


class GameEvent(BaseModel):
    type: str
    data: dict
    timestamp: str


# ==================== 连接管理器 ====================
class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.game_subscriptions: Dict[str, set] = {}  # game_id -> {connection_ids}
    
    async def connect(self, websocket: WebSocket, game_id: str, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        if game_id not in self.game_subscriptions:
            self.game_subscriptions[game_id] = set()
        self.game_subscriptions[game_id].add(client_id)
    
    def disconnect(self, client_id: str, game_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if game_id in self.game_subscriptions:
            self.game_subscriptions[game_id].discard(client_id)
    
    async def send_event(self, client_id: str, event: dict):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(event)
            except:
                pass
    
    async def broadcast_to_game(self, game_id: str, event: dict):
        if game_id in self.game_subscriptions:
            for client_id in self.game_subscriptions[game_id]:
                await self.send_event(client_id, event)


manager = ConnectionManager()


# ==================== 游戏管理器 ====================
class GameManager:
    """游戏实例管理器"""
    
    def __init__(self):
        self.games: Dict[str, GameState] = {}
        self.client_games: Dict[str, str] = {}  # client_id -> game_id
    
    def create_game(self, player_name: str = "Player") -> str:
        game_id = str(uuid.uuid4())[:8]
        self.games[game_id] = GameState()
        
        # 重命名人类玩家为指定名称
        if player_name != "Player":
            game = self.games[game_id]
            if "Player" in game.agents:
                game.agents[player_name] = game.agents.pop("Player")
                game.agents[player_name].name = player_name
                game.human_player = player_name
        
        return game_id
    
    def get_game(self, game_id: str) -> Optional[GameState]:
        return self.games.get(game_id)
    
    def get_player_role(self, game_id: str, player_name: str) -> str:
        game = self.get_game(game_id)
        if game and player_name in game.agents:
            return game.agents[player_name].role.value
        return "unknown"


game_mgr = GameManager()


# ==================== FastAPI 应用 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    print("🚀 AI心理博弈游戏服务启动")
    print("   API: http://localhost:18080")
    print("   WS:  ws://localhost:18080/ws/{game_id}/{client_id}")
    yield
    # 关闭时
    print("🛑 服务关闭")


app = FastAPI(
    title="AI Psychological Game API",
    description="AI原生心理博弈社交推理游戏后端服务",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API 端点 ====================
@app.post("/api/game/new", response_model=NewGameResponse)
async def create_game(request: NewGameRequest):
    """创建新游戏"""
    game_id = game_mgr.create_game(request.player_name)
    game = game_mgr.get_game(game_id)
    
    # 返回游戏初始状态
    players = []
    for name, agent in game.agents.items():
        players.append({
            "name": name,
            "alive": agent.alive,
            "role": agent.role.value if agent.is_human else "hidden"  # 人类玩家看不到AI角色
        })
    
    return NewGameResponse(
        game_id=game_id,
        day=game.day,
        phase=game.phase.value,
        players=players,
        your_role=game.agents[request.player_name].role.value
    )


@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    """获取当前游戏状态"""
    game = game_mgr.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    players = []
    for name, agent in game.agents.items():
        players.append({
            "name": name,
            "alive": agent.alive,
            "role": agent.role.value if agent.is_human else "hidden",
            "emotional_state": agent.emotional_state.to_dict(),
            "suspicion_scores": {k: v for k, v in agent.suspicion_scores.items() if k != name}
        })
    
    return {
        "game_id": game_id,
        "day": game.day,
        "phase": game.phase.value,
        "turn": game.turn,
        "players": players,
        "winner": game.winner
    }


@app.post("/api/game/{game_id}/player/say")
async def player_say(game_id: str, request: PlayerSayRequest):
    """玩家发言"""
    game = game_mgr.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    if game.phase != GamePhase.DAY_DISCUSSION:
        raise HTTPException(status_code=400, detail="当前不是讨论阶段")
    
    # 获取人类玩家
    human = None
    for name, agent in game.agents.items():
        if agent.is_human:
            human = agent
            break
    
    if not human:
        raise HTTPException(status_code=400, detail="未找到人类玩家")
    
    # 记录玩家发言
    print(f"【{human.name}】说：「{request.statement}」")
    
    # 广播发言事件
    await manager.broadcast_to_game(game_id, {
        "type": "player_statement",
        "data": {
            "player": human.name,
            "statement": request.statement,
            "timestamp": datetime.now().isoformat()
        }
    })
    
    return {"status": "ok", "message": "发言已提交"}


@app.post("/api/game/{game_id}/player/vote")
async def player_vote(game_id: str, request: PlayerVoteRequest):
    """玩家投票"""
    game = game_mgr.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    if game.phase != GamePhase.VOTING:
        raise HTTPException(status_code=400, detail="当前不是投票阶段")
    
    # 获取人类玩家
    human = None
    for name, agent in game.agents.items():
        if agent.is_human:
            human = agent
            break
    
    if not human:
        raise HTTPException(status_code=400, detail="未找到人类玩家")
    
    if request.target not in game.agents:
        raise HTTPException(status_code=400, detail="投票目标不存在")
    
    # 记录投票
    print(f"【{human.name}】投票给了 {request.target}")
    
    # 广播投票事件
    await manager.broadcast_to_game(game_id, {
        "type": "player_vote",
        "data": {
            "player": human.name,
            "target": request.target,
            "timestamp": datetime.now().isoformat()
        }
    })
    
    return {"status": "ok", "message": "投票已提交"}


# ==================== WebSocket 端点 ====================
@app.websocket("/ws/{game_id}/{client_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, client_id: str):
    """WebSocket事件流"""
    game = game_mgr.get_game(game_id)
    if not game:
        await websocket.close(code=4004)
        return
    
    await manager.connect(websocket, game_id, client_id)
    game_mgr.client_games[client_id] = game_id
    
    try:
        # 发送初始状态
        await manager.send_event(client_id, {
            "type": "game_start",
            "data": {
                "game_id": game_id,
                "day": game.day,
                "phase": game.phase.value,
                "players": [
                    {"name": name, "alive": agent.alive}
                    for name, agent in game.agents.items()
                ]
            }
        })
        
        # 主循环：推进游戏
        while True:
            await asyncio.sleep(0.5)
            
            # 检查游戏是否结束
            if game.check_game_end():
                await manager.broadcast_to_game(game_id, {
                    "type": "game_over",
                    "data": {
                        "winner": game.winner,
                        "day": game.day
                    }
                })
                break
            
            # 根据阶段执行
            if game.phase == GamePhase.DAY_DISCUSSION:
                await run_discussion_turn(game, game_id)
                
            elif game.phase == GamePhase.VOTING:
                await run_voting_phase(game, game_id)
                
            elif game.phase == GamePhase.NIGHT_ACTION:
                await run_night_phase(game, game_id)
                game.day += 1
                game.phase = GamePhase.DAY_DISCUSSION
                
                await manager.broadcast_to_game(game_id, {
                    "type": "new_day",
                    "data": {
                        "day": game.day
                    }
                })
    
    except WebSocketDisconnect:
        print(f"客户端 {client_id} 断开连接")
    finally:
        manager.disconnect(client_id, game_id)


async def run_discussion_turn(game: GameState, game_id: str):
    """执行讨论阶段的一轮发言"""
    alive = game.get_alive_players()
    random.shuffle(alive)
    
    for speaker in alive:
        if not game.agents[speaker].alive:
            continue
        
        # 跳过人类玩家（等待HTTP请求）
        if game.agents[speaker].is_human:
            continue
        
        agent = game.agents[speaker]
        
        # 生成发言
        visible_state = {
            "phase": "讨论",
            "day": game.day,
            "human_player": "Player"
        }
        
        statement = game.llm_interface.generate_statement(agent, visible_state)
        
        # 广播发言
        await manager.broadcast_to_game(game_id, {
            "type": "ai_statement",
            "data": {
                "player": agent.name,
                "role": agent.role.value,
                "statement": statement,
                "timestamp": datetime.now().isoformat()
            }
        })
        
        print(f"【{agent.name}】（{agent.role.value}）说：「{statement}」")
        
        # 更新其他人的心理状态
        for other_name in alive:
            if other_name == speaker:
                continue
            other = game.agents[other_name]
            
            # 发言中提到某人
            for name in game.agents:
                if name in statement and name != speaker:
                    impact = random.uniform(0.1, 0.3)
                    other.update_psychology("accused", speaker, name, impact)
        
        await asyncio.sleep(1)  # 模拟思考时间
    
    # 发言结束，切换到投票阶段
    game.phase = GamePhase.VOTING
    await manager.broadcast_to_game(game_id, {
        "type": "phase_change",
        "data": {
            "phase": "voting"
        }
    })


async def run_voting_phase(game: GameState, game_id: str):
    """执行投票阶段"""
    alive = game.get_alive_players()
    votes: Dict[str, str] = {}
    
    for name in alive:
        if not game.agents[name].alive:
            continue
        
        if game.agents[name].is_human:
            # 等待人类玩家投票（通过HTTP）
            continue
        else:
            # AI投票
            target = game.agents[name].make_vote_decision(alive)
            votes[name] = target
    
    if len(votes) < len([a for a in game.agents.values() if a.alive and not a.is_human]):
        # 等待人类投票
        return
    
    # 计算投票结果
    vote_counts: Dict[str, int] = {}
    for voter, target in votes.items():
        vote_counts[target] = vote_counts.get(target, 0) + 1
    
    await manager.broadcast_to_game(game_id, {
        "type": "vote_results",
        "data": {
            "votes": votes,
            "counts": vote_counts
        }
    })
    
    # 找出被淘汰者
    if vote_counts:
        max_votes = max(vote_counts.values())
        candidates = [p for p, c in vote_counts.items() if c == max_votes]
        
        if len(candidates) == 1:
            eliminated = candidates[0]
            game.agents[eliminated].alive = False
            
            await manager.broadcast_to_game(game_id, {
                "type": "player_eliminated",
                "data": {
                    "player": eliminated,
                    "role": game.agents[eliminated].role.value
                }
            })
            
            print(f"\n⚠️  {eliminated} 被投票淘汰！")
            print(f"  真实身份：{game.agents[eliminated].role.value}")
    
    # 切换到夜晚阶段
    game.phase = GamePhase.NIGHT_ACTION
    await manager.broadcast_to_game(game_id, {
        "type": "phase_change",
        "data": {
            "phase": "night"
        }
    })


async def run_night_phase(game: GameState, game_id: str):
    """执行夜晚阶段"""
    alive = game.get_alive_players()
    wolves = [n for n in alive if game.agents[n].role == Role.WOLF]
    
    if not wolves:
        return
    
    # 狼人决策
    kill_target = None
    for wolf_name in wolves:
        agent = game.agents[wolf_name]
        target = agent.wolf_night_action(alive)
        
        if target:
            kill_target = target
            break
    
    if kill_target:
        game.agents[kill_target].alive = False
        
        await manager.broadcast_to_game(game_id, {
            "type": "night_kill",
            "data": {
                "victim": kill_target,
                "role": game.agents[kill_target].role.value
            }
        })
        
        print(f"\n🌙 夜里，{kill_target} 被发现死亡！")
        print(f"  真实身份：{game.agents[kill_target].role.value}")


# ==================== 健康检查 ====================
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ai-psychological-game"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18080)
