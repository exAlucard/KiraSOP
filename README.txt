Anti-aggro v9: SWEEP priority

Replace:
  D:\KiraSOP\la2_bot\actions\targeting.py
  D:\KiraSOP\la2_bot\utils\threat_watcher.py

Behavior after target death:
  1. watcher starts immediately and may detect incoming damage;
  2. anti-aggro retarget is blocked by a sweep gate;
  3. bot sends SWEEP twice (same reliability pattern as existing code);
  4. gate opens;
  5. if threat was already confirmed, anti-aggro immediately proceeds to target acquisition/ATTACK;
  6. remaining LOOT may be interrupted by anti-aggro.

Expected log order when incoming damage is detected early:
  TARGET_DEATH_TRANSITION
  POST_KILL_SWEEP_GATE_CLOSED
  THREAT_DEFERRED_UNTIL_SWEEP
  POST_KILL_SWEEP_COMMAND index=1
  POST_KILL_SWEEP_COMMAND index=2
  POST_KILL_SWEEP_GATE_OPENED
  THREAT_SWEEP_BARRIER_RELEASED
  WATCH_PHASE ... ACQUIRING
  ACQUIRE_COMMAND / EXISTING_TARGET_CLAIMED
  ANTIAGGRO_ATTACK_COMMAND
