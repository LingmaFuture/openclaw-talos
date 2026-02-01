import { useGameStore } from '../store/gameStore';

const API_BASE = 'http://localhost:18080';
const WS_BASE = 'ws://localhost:18080/ws';

export class GameWebSocket {
  private ws: WebSocket | null = null;
  private gameId: string = '';
  private clientId: string = '';
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  connect(gameId: string, clientId: string) {
    this.gameId = gameId;
    this.clientId = clientId;
    
    const wsUrl = `${WS_BASE}/${gameId}/${clientId}`;
    this.ws = new WebSocket(wsUrl);
    
    this.ws.onopen = () => {
      console.log('WebSocket connected');
      useGameStore.getState().setConnected(true);
      this.reconnectAttempts = 0;
    };
    
    this.ws.onclose = () => {
      console.log('WebSocket disconnected');
      useGameStore.getState().setConnected(false);
      this.attemptReconnect();
    };
    
    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      useGameStore.getState().setError('连接错误');
    };
    
    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (e) {
        console.error('Failed to parse message:', e);
      }
    };
  }

  private handleMessage(data: any) {
    const store = useGameStore.getState();
    
    switch (data.type) {
      case 'game_start':
        store.setGameId(data.data.game_id);
        store.setDay(data.data.day);
        store.setPlayers(data.data.players);
        break;
        
      case 'ai_statement':
        store.addStatement({
          player: data.data.player,
          role: data.data.role,
          statement: data.data.statement,
          timestamp: data.data.timestamp,
        });
        break;
        
      case 'player_statement':
        store.addStatement({
          player: data.data.player,
          role: 'player',
          statement: data.data.statement,
          timestamp: data.data.timestamp,
        });
        break;
        
      case 'phase_change':
        store.setPhase(data.data.phase);
        break;
        
      case 'vote_results':
        store.setVotes(data.data.votes);
        break;
        
      case 'player_eliminated':
        store.setPlayers(
          store.players.map((p) =>
            p.name === data.data.player ? { ...p, alive: false } : p
          )
        );
        break;
        
      case 'night_kill':
        store.setPlayers(
          store.players.map((p) =>
            p.name === data.data.victim ? { ...p, alive: false } : p
          )
        );
        break;
        
      case 'new_day':
        store.setDay(data.data.day);
        store.setPhase('day_discussion');
        break;
        
      case 'game_over':
        store.setWinner(data.data.winner);
        break;
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      console.log(`Reconnecting... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
      setTimeout(() => this.connect(this.gameId, this.clientId), 2000);
    }
  }

  sendStatement(statement: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ statement }));
    }
  }

  sendVote(target: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ target }));
    }
  }

  disconnect() {
    this.ws?.close();
    this.ws = null;
  }
}

export const gameWS = new GameWebSocket();

// API functions
export async function createGame(playerName: string) {
  const response = await fetch(`${API_BASE}/api/game/new`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_name: playerName }),
  });
  
  if (!response.ok) {
    throw new Error('Failed to create game');
  }
  
  return response.json();
}

export async function getGameState(gameId: string) {
  const response = await fetch(`${API_BASE}/api/game/${gameId}/state`);
  
  if (!response.ok) {
    throw new Error('Failed to get game state');
  }
  
  return response.json();
}
