import React, { useEffect, useState, useRef } from 'react';
import { useGameStore } from '../store/gameStore';
import { createGame, gameWS } from '../services/gameAPI';

export function GameUI() {
  const store = useGameStore();
  const [playerName, setPlayerName] = useState('Player');
  const [inputStatement, setInputStatement] = useState('');
  const [showVotePanel, setShowVotePanel] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [store.statements]);

  const handleCreateGame = async () => {
    store.setLoading(true);
    store.setError(null);
    
    try {
      const result = await createGame(playerName);
      store.setGameId(result.game_id);
      store.setDay(result.day);
      store.setPhase(result.phase);
      store.setPlayers(result.players);
      store.setYourRole(result.your_role);
      
      // Connect WebSocket
      const clientId = `client_${Date.now()}`;
      gameWS.connect(result.game_id, clientId);
    } catch (e) {
      store.setError('创建游戏失败，请检查后端服务是否运行');
      console.error(e);
    } finally {
      store.setLoading(false);
    }
  };

  const handleSendStatement = () => {
    if (!inputStatement.trim()) return;
    
    gameWS.sendStatement(inputStatement);
    store.addStatement({
      player: playerName,
      role: 'player',
      statement: inputStatement,
      timestamp: new Date().toISOString(),
    });
    setInputStatement('');
  };

  const handleVote = (target: string) => {
    gameWS.sendVote(target);
    setShowVotePanel(false);
  };

  // Phase display names
  const phaseNames: Record<string, string> = {
    day_discussion: '讨论阶段',
    voting: '投票阶段',
    night_action: '夜晚阶段',
    game_over: '游戏结束',
  };

  // Render game screen
  if (store.gameId) {
    const alivePlayers = store.players.filter((p) => p.alive);
    const eliminatedPlayers = store.players.filter((p) => !p.alive);

    return (
      <div className="min-h-screen p-4 flex gap-4 max-w-6xl mx-auto">
        {/* Left Panel - Chat/Discussion */}
        <div className="flex-1 flex flex-col bg-gray-800/50 rounded-xl overflow-hidden">
          {/* Header */}
          <div className="bg-gray-900/80 p-4 border-b border-gray-700">
            <div className="flex items-center justify-between">
              <h1 className="text-xl font-bold text-white">
                第 {store.day} 天 - {phaseNames[store.phase]}
              </h1>
              <div className={`px-3 py-1 rounded-full text-sm ${
                store.isConnected 
                  ? 'bg-green-500/20 text-green-400' 
                  : 'bg-red-500/20 text-red-400'
              }`}>
                {store.isConnected ? '已连接' : '未连接'}
              </div>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {store.statements.map((stmt, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-lg ${
                  stmt.role === 'player'
                    ? 'bg-blue-500/20 ml-8'
                    : stmt.role === 'wolf'
                    ? 'bg-red-500/20'
                    : 'bg-gray-700/50'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-bold text-white">{stmt.player}</span>
                  {stmt.role === 'wolf' && (
                    <span className="text-xs bg-red-500/30 text-red-300 px-2 py-0.5 rounded">
                      狼人
                    </span>
                  )}
                </div>
                <p className="text-gray-200">{stmt.statement}</p>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="p-4 bg-gray-900/80 border-t border-gray-700">
            {store.phase === 'voting' ? (
              <button
                onClick={() => setShowVotePanel(!showVotePanel)}
                className="w-full py-3 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition-colors"
              >
                投票选择
              </button>
            ) : (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inputStatement}
                  onChange={(e) => setInputStatement(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleSendStatement()}
                  placeholder="输入你的发言..."
                  className="flex-1 px-4 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                  disabled={store.phase !== 'day_discussion'}
                />
                <button
                  onClick={handleSendStatement}
                  disabled={!inputStatement.trim() || store.phase !== 'day_discussion'}
                  className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                >
                  发送
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Right Panel - Status */}
        <div className="w-72 flex flex-col gap-4">
          {/* Player List */}
          <div className="bg-gray-800/50 rounded-xl p-4">
            <h2 className="font-bold text-white mb-3">存活玩家</h2>
            <div className="space-y-2">
              {alivePlayers.map((player) => (
                <div
                  key={player.name}
                  className={`flex items-center justify-between p-2 rounded ${
                    player.name === playerName
                      ? 'bg-blue-500/30 border border-blue-500/50'
                      : 'bg-gray-700/50'
                  }`}
                >
                  <span className="text-white">
                    {player.name}
                    {player.name === playerName && ' (你)'}
                  </span>
                  <div className="flex items-center gap-1">
                    {store.votes[player.name] && (
                      <span className="text-xs text-red-400">
                        票: {store.votes[player.name]}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Eliminated Players */}
          {eliminatedPlayers.length > 0 && (
            <div className="bg-gray-800/50 rounded-xl p-4">
              <h2 className="font-bold text-red-400 mb-3">已淘汰</h2>
              <div className="space-y-2">
                {eliminatedPlayers.map((player) => (
                  <div
                    key={player.name}
                    className="flex items-center justify-between p-2 rounded bg-gray-900/50 text-gray-500 line-through"
                  >
                    <span>{player.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Game Info */}
          <div className="bg-gray-800/50 rounded-xl p-4">
            <h2 className="font-bold text-white mb-3">游戏信息</h2>
            <div className="space-y-2 text-sm text-gray-300">
              <p>你的角色: <span className="text-blue-400">{store.yourRole}</span></p>
              <p>存活: {alivePlayers.length} 人</p>
              <p>狼人数量: 1 (隐藏)</p>
            </div>
          </div>

          {/* Vote Panel */}
          {showVotePanel && store.phase === 'voting' && (
            <div className="bg-gray-800/50 rounded-xl p-4">
              <h2 className="font-bold text-white mb-3">投票给谁？</h2>
              <div className="space-y-2">
                {alivePlayers
                  .filter((p) => p.name !== playerName)
                  .map((player) => (
                    <button
                      key={player.name}
                      onClick={() => handleVote(player.name)}
                      className="w-full p-3 bg-red-600/50 hover:bg-red-600 text-white rounded-lg transition-colors"
                    >
                      {player.name}
                    </button>
                  ))}
              </div>
            </div>
          )}

          {/* Game Over */}
          {store.phase === 'game_over' && (
            <div className="bg-gray-800/50 rounded-xl p-4 text-center">
              <h2 className={`font-bold text-xl mb-2 ${
                store.winner === 'villagers' ? 'text-green-400' : 'text-red-400'
              }`}>
                {store.winner === 'villagers' ? '🏆 村民获胜！' : '🐺 狼人获胜！'}
              </h2>
              <button
                onClick={() => {
                  gameWS.disconnect();
                  useGameStore.getState().reset();
                }}
                className="mt-4 px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
              >
                再来一局
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Render start screen
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="bg-gray-800/50 rounded-2xl p-8 max-w-md w-full">
        <h1 className="text-3xl font-bold text-white text-center mb-2">
          🐺👥 心理博弈
        </h1>
        <p className="text-gray-400 text-center mb-8">
          AI 社交推理游戏
        </p>

        {store.error && (
          <div className="mb-4 p-3 bg-red-500/20 border border-red-500/50 rounded-lg text-red-400 text-sm">
            {store.error}
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-gray-300 mb-2">你的名字</label>
            <input
              type="text"
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              className="w-full px-4 py-3 bg-gray-800 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-blue-500"
              placeholder="输入名字"
            />
          </div>

          <button
            onClick={handleCreateGame}
            disabled={store.isLoading}
            className="w-full py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 text-white rounded-lg font-medium transition-all"
          >
            {store.isLoading ? '创建中...' : '开始游戏'}
          </button>
        </div>

        <div className="mt-8 text-xs text-gray-500 text-center">
          <p>规则：找出并投票淘汰狼人</p>
          <p className="mt-1">5 AI 角色 (4 村民 + 1 狼人)</p>
        </div>
      </div>
    </div>
  );
}
