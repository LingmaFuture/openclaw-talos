# AI 心理博弈社交推理游戏

## 项目结构

```
openclaw-talos/
├── backend/              # FastAPI 后端服务
│   ├── app.py           # FastAPI 主应用 + WebSocket
│   ├── engine.py        # 游戏引擎核心逻辑
│   ├── requirements.txt # Python 依赖
│   └── .env.example     # 环境变量示例
├── frontend/             # React + Vite 前端
│   ├── src/
│   │   ├── GameUI.tsx   # 游戏主界面
│   │   ├── store/       # Zustand 状态管理
│   │   └── services/    # API + WebSocket 服务
│   └── vite.config.ts   # Vite 配置
└── README.md
```

## 快速开始

### 1. 启动后端服务

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export OPENROUTER_API_KEY="your-api-key"

# 启动服务 (端口 18080)
python app.py
```

### 2. 启动前端开发服务器

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器 (端口 15173)
npm run dev
```

### 3. 访问游戏

打开浏览器访问：`http://localhost:15173`

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/game/new` | POST | 创建新游戏 |
| `/api/game/{id}/state` | GET | 获取游戏状态 |
| `/api/game/{id}/player/say` | POST | 玩家发言 |
| `/api/game/{id}/player/vote` | POST | 玩家投票 |
| `/ws/{game_id}/{client_id}` | WebSocket | 事件流 |

## 游戏规则

- **角色**：5 AI (4 村民 + 1 狼人) + 1 人类玩家
- **阶段**：讨论 → 投票 → 夜晚
- **目标**：村民找出并投票淘汰狼人

## 技术栈

- **后端**：FastAPI + WebSocket + OpenRouter API
- **前端**：React + TypeScript + Vite + Tailwind + Zustand
