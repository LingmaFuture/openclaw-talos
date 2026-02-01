import { create } from 'zustand';

export interface Player {
  name: string;
  alive: boolean;
  role: string;
  emotional_state?: {
    anger: number;
    fear: number;
    confidence: number;
  };
  suspicion_scores?: Record<string, number>;
}

export interface GameState {
  gameId: string | null;
  day: number;
  phase: 'day_discussion' | 'voting' | 'night_action' | 'game_over';
  players: Player[];
  yourRole: string;
  statements: Statement[];
  votes: Record<string, string>;
  winner: string | null;
  isConnected: boolean;
  isLoading: boolean;
  error: string | null;
}

export interface Statement {
  player: string;
  role: string;
  statement: string;
  timestamp: string;
}

interface GameStore extends GameState {
  // Actions
  setGameId: (id: string) => void;
  setDay: (day: number) => void;
  setPhase: (phase: GameState['phase']) => void;
  setPlayers: (players: Player[]) => void;
  setYourRole: (role: string) => void;
  addStatement: (stmt: Statement) => void;
  setVotes: (votes: Record<string, string>) => void;
  setWinner: (winner: string | null) => void;
  setConnected: (connected: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useGameStore = create<GameStore>((set) => ({
  // Initial state
  gameId: null,
  day: 1,
  phase: 'day_discussion',
  players: [],
  yourRole: 'villager',
  statements: [],
  votes: {},
  winner: null,
  isConnected: false,
  isLoading: false,
  error: null,

  // Actions
  setGameId: (id) => set({ gameId: id }),
  setDay: (day) => set({ day }),
  setPhase: (phase) => set({ phase }),
  setPlayers: (players) => set({ players }),
  setYourRole: (role) => set({ yourRole: role }),
  addStatement: (stmt) => set((state) => ({ 
    statements: [...state.statements, stmt] 
  })),
  setVotes: (votes) => set({ votes }),
  setWinner: (winner) => set({ winner, phase: 'game_over' }),
  setConnected: (connected) => set({ isConnected: connected }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
  reset: () => set({
    gameId: null,
    day: 1,
    phase: 'day_discussion',
    players: [],
    statements: [],
    votes: {},
    winner: null,
    isConnected: false,
  }),
}));
